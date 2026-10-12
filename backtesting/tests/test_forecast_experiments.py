from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta
from hashlib import sha256

import pytest

from backtesting.forecast import ForecastObservation
from backtesting.forecast_experiments import build_experiment_manifest, compare_challenger_to_champion, compare_selection_candidate_to_champion
from backtesting.forecast_feature_model import build_continuous_feature_report, fit_continuous_feature_model
from backtesting.walk_forward import WalkForwardSettings


def _observations(count: int = 180) -> list[ForecastObservation]:
    start = date(2020, 1, 1)
    return [
        ForecastObservation(
            as_of=start + timedelta(days=index),
            symbol=f"S{index % 5}",
            signal_score=70.0,
            forward_return_3m=0.3 if index % 2 else -0.1,
            max_drawdown_3m=-0.1 if index % 2 else -0.3,
            label_version="next_open_low_v2",
            feature_schema_version="continuous_regime_v1",
            feature_values={"feature": float(index % 3), "market": 1.0},
            market_regime="neutral",
        )
        for index in range(count)
    ]


@pytest.fixture(autouse=True)
def small_feature_model(monkeypatch: pytest.MonkeyPatch) -> None:
    from backtesting import forecast_feature_model

    config = forecast_feature_model.load_forecast_feature_config().copy()
    config["logistic_regression"] = {"regularization_candidates": [0.1], "minimum_training_observations": 30, "max_iterations": 100}
    monkeypatch.setattr(forecast_feature_model, "load_forecast_feature_config", lambda: config)


def _report() -> dict[str, object]:
    model = fit_continuous_feature_model(
        _observations(),
        walk_forward=WalkForwardSettings(training_sessions=40, validation_sessions=20, test_sessions=20, step_sessions=20),
        point_in_time_certified=True,
    )
    return build_continuous_feature_report(model)


def _manifest(report: dict[str, object], name: str = "candidate") -> dict[str, object]:
    return build_experiment_manifest(
        report,
        name=name,
        hypothesis="Test the locked continuous feature baseline.",
        observations_sha256="a" * 64,
        report_sha256="b" * 64,
    )


def test_report_has_a_stable_walk_forward_protocol_fingerprint() -> None:
    first = _report()
    second = _report()

    assert first["evaluation_protocol"] == second["evaluation_protocol"]
    assert first["evaluation_protocol"]["fingerprint"] == sha256(
        __import__("json").dumps(first["evaluation_protocol"]["folds"], sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def test_manifest_records_hashes_and_fail_closed_eligibility() -> None:
    report = _report()
    report["calibration_status"] = "unavailable"
    report["promotion_gate"]["result"] = "unavailable"

    manifest = _manifest(report)

    assert manifest["artifacts"] == {"observations_sha256": "a" * 64, "report_sha256": "b" * 64}
    assert manifest["eligibility"]["forecast_eligible"] is False
    assert manifest["model"]["evaluation_protocol"]["fingerprint"]


def test_challenger_requires_matching_label_coverage_and_protocol() -> None:
    champion = _manifest(_report(), "champion")
    challenger = deepcopy(champion)
    challenger["model"]["label_version"] = "different_label_v1"

    decision = compare_challenger_to_champion(champion, challenger)

    assert decision["decision"] == "retain"
    assert decision["reason"] == "incompatible_experiment_protocol"
    assert decision["compatibility_issues"] == ["label_version"]


def test_challenger_must_win_both_primary_brier_metrics() -> None:
    champion = _manifest(_report(), "champion")
    challenger = deepcopy(champion)
    challenger["eligibility"]["forecast_eligible"] = True
    challenger["eligibility"]["calibration_status"] = "validated"
    challenger["out_of_sample_metrics"]["upside_brier_score"] = champion["out_of_sample_metrics"]["upside_brier_score"] - 0.002
    challenger["out_of_sample_metrics"]["downside_brier_score"] = champion["out_of_sample_metrics"]["downside_brier_score"] + 0.002

    decision = compare_challenger_to_champion(champion, challenger)

    assert decision["decision"] == "retain"
    assert decision["reason"] == "challenger_does_not_win_both_primary_metrics"


def test_challenger_promotes_only_when_certified_and_both_metrics_clear_threshold() -> None:
    champion = _manifest(_report(), "champion")
    challenger = deepcopy(champion)
    challenger["eligibility"]["forecast_eligible"] = True
    challenger["eligibility"]["calibration_status"] = "validated"
    challenger["out_of_sample_metrics"]["upside_brier_score"] = champion["out_of_sample_metrics"]["upside_brier_score"] - 0.002
    challenger["out_of_sample_metrics"]["downside_brier_score"] = champion["out_of_sample_metrics"]["downside_brier_score"] - 0.002

    decision = compare_challenger_to_champion(champion, challenger)

    assert decision["decision"] == "promote"
    assert decision["brier_improvements_over_champion"] == {
        "upside_brier_score": 0.002,
        "downside_brier_score": 0.002,
    }


def test_selection_candidate_can_replace_an_experimental_champion_without_promoting_forecasts() -> None:
    champion = _manifest(_report(), "champion")
    candidate = deepcopy(champion)
    candidate["eligibility"]["forecast_eligible"] = False
    candidate["out_of_sample_metrics"]["upside_brier_score"] = champion["out_of_sample_metrics"]["upside_brier_score"] - 0.002
    candidate["out_of_sample_metrics"]["downside_brier_score"] = champion["out_of_sample_metrics"]["downside_brier_score"] - 0.002

    decision = compare_selection_candidate_to_champion(champion, candidate)

    assert decision["decision"] == "replace"
    assert decision["numeric_forecast_promotion"] == "not_evaluated"
