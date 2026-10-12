from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from backtesting.forecast import ForecastObservation
from backtesting.forecast_holdout import build_outer_holdout_contract, split_outer_holdout
from backtesting.forecast_provenance import build_yfinance_price_provenance
from tools import evaluate_final_holdout


def _observation(as_of: date, index: int) -> ForecastObservation:
    feature = float(index % 2)
    return ForecastObservation(
        as_of=as_of,
        symbol=f"S{index % 5}",
        signal_score=80 if feature else 20,
        forward_return_3m=0.30 if feature else -0.10,
        max_drawdown_3m=-0.10 if feature else -0.30,
        label_version="next_open_low_v2",
        entry_date=as_of + timedelta(days=1),
        exit_date=as_of + timedelta(days=64),
        entry_price=100,
        exit_price=130,
        feature_schema_version="continuous_regime_v1",
        feature_values={"feature": feature, "market": 1.0, "regime_risk_on": float(index % 3 == 0)},
        market_regime="risk_on" if index % 3 == 0 else "neutral",
    )


@pytest.fixture(autouse=True)
def stub_holdout_model(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_fit(
        selection_observations,
        *,
        holdout_start: date,
        point_in_time_certified: bool,
    ):
        selection = list(selection_observations)
        trained_through = max(item.as_of for item in selection)
        metadata = {
            "model_version": "stub-model-v1",
            "label_version": selection[0].label_version,
            "feature_schema_version": selection[0].feature_schema_version,
            "feature_names": ["feature", "market", "regime_risk_on"],
            "holdout_start": holdout_start.isoformat(),
            "trained_through": trained_through.isoformat(),
            "selection_fingerprint": evaluate_final_holdout.forecast_observation_fingerprint(selection),
            "selection_observation_count": len(selection),
            "selection_symbol_count": len({item.symbol for item in selection}),
            "selection_fold_count": 3,
            "point_in_time_certified": point_in_time_certified,
            "selected_configuration": {
                "upside": {"regularization": 0.1, "feature_model_weight": 1.0},
                "downside": {"regularization": 0.1, "feature_model_weight": 1.0},
            },
            "selection_protocol": {"minimum_brier_improvement": 0.01},
        }
        return SimpleNamespace(
            model_version="stub-model-v1",
            label_version=selection[0].label_version,
            feature_schema_version=selection[0].feature_schema_version,
            metadata=lambda: metadata,
        )

    def fake_score(artifact, final_holdout_observations, *, bootstrap_samples: int):
        rows = list(final_holdout_observations)
        return {
            "schema_version": "forecast_final_holdout_report_v1",
            "experimental": True,
            "model_version": artifact.model_version,
            "label_version": artifact.label_version,
            "feature_schema_version": artifact.feature_schema_version,
            "calibration_status": "unavailable",
            "numeric_forecast_status": "unavailable",
            "trained_artifact": artifact.metadata(),
            "final_holdout": {
                "observation_count": len(rows),
                "symbol_count": len({item.symbol for item in rows}),
                "from": min(item.as_of for item in rows).isoformat(),
                "through": max(item.as_of for item in rows).isoformat(),
                "fingerprint": evaluate_final_holdout.forecast_observation_fingerprint(rows),
            },
            "out_of_sample_metrics": {"out_of_sample_count": len(rows)},
            "calibration": {"bootstrap_samples": bootstrap_samples},
            "promotion_gate": {"result": "unavailable"},
        }

    monkeypatch.setattr(evaluate_final_holdout, "fit_frozen_continuous_feature_artifact", fake_fit)
    monkeypatch.setattr(evaluate_final_holdout, "score_final_holdout", fake_score)


def _write_case(tmp_path: Path, *, holdout_start: date) -> dict[str, Path]:
    selection_start = date(2020, 1, 1)
    final_start = holdout_start + timedelta(days=2)
    selection = [_observation(selection_start + timedelta(days=index), index) for index in range(6)]
    final_holdout = [_observation(final_start + timedelta(days=index), index + 10) for index in range(4)]
    split = split_outer_holdout([*selection, *final_holdout], holdout_start=holdout_start)
    contract = build_outer_holdout_contract(split)
    selection_path = tmp_path / "selection.jsonl"
    final_path = tmp_path / "final.jsonl"
    contract_path = tmp_path / "contract.json"
    provenance_path = tmp_path / "provenance.json"
    output_path = tmp_path / "report.json"
    consumption_path = tmp_path / "consumption.json"
    _write_jsonl(selection_path, split.selection)
    _write_jsonl(final_path, split.final_holdout)
    contract_path.write_text(json.dumps(contract, indent=2, default=str) + "\n", encoding="utf-8")
    provenance = build_yfinance_price_provenance(
        requested_start=date(2020, 1, 1),
        requested_end=holdout_start,
        symbols_requested=5,
        symbols_with_observations=5,
        run_id="test-run",
        feature_schema_version="continuous_regime_v1",
        benchmark_symbols=["SPY"],
    )
    provenance_path.write_text(provenance.model_dump_json(indent=2), encoding="utf-8")
    return {
        "selection": selection_path,
        "final": final_path,
        "contract": contract_path,
        "provenance": provenance_path,
        "output": output_path,
        "consumption": consumption_path,
    }


def _argv(paths: dict[str, Path], *, bootstrap_samples: int = 20) -> list[str]:
    return [
        "--selection",
        str(paths["selection"]),
        "--final-holdout",
        str(paths["final"]),
        "--holdout-contract",
        str(paths["contract"]),
        "--provenance",
        str(paths["provenance"]),
        "--output",
        str(paths["output"]),
        "--bootstrap-samples",
        str(bootstrap_samples),
        "--consumption-registry",
        str(paths["consumption"]),
    ]


def _write_jsonl(path: Path, rows: tuple[ForecastObservation, ...]) -> None:
    with path.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(row.model_dump_json() + "\n")


def test_duplicate_key_is_rejected_before_loading_final_holdout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = _write_case(tmp_path, holdout_start=date(2025, 1, 1))

    assert evaluate_final_holdout.main(_argv(paths)) == 0

    real_load = evaluate_final_holdout._load_observations

    def guarded(path: Path):
        if path == paths["final"]:
            raise AssertionError("final holdout should not be loaded")
        return real_load(path)

    monkeypatch.setattr(evaluate_final_holdout, "_load_observations", guarded)
    with pytest.raises(ValueError, match="identical final-holdout consumption key already consumed"):
        evaluate_final_holdout.main(_argv(paths))


def test_distinct_key_is_still_blocked_for_consumed_holdout_before_loading_outcomes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _write_case(tmp_path, holdout_start=date(2025, 1, 1))

    assert evaluate_final_holdout.main(_argv(paths, bootstrap_samples=20)) == 0

    real_load = evaluate_final_holdout._load_observations

    def guarded(path: Path):
        if path == paths["final"]:
            raise AssertionError("final holdout should not be loaded")
        return real_load(path)

    monkeypatch.setattr(evaluate_final_holdout, "_load_observations", guarded)
    with pytest.raises(ValueError, match="already reserved or consumed by another artifact or evaluation configuration"):
        evaluate_final_holdout.main(_argv(paths, bootstrap_samples=21))


def test_legacy_2023_holdout_is_seeded_as_consumed_before_final_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _write_case(tmp_path, holdout_start=date(2023, 1, 1))

    real_load = evaluate_final_holdout._load_observations

    def guarded(path: Path):
        if path == paths["final"]:
            raise AssertionError("final holdout should not be loaded")
        return real_load(path)

    monkeypatch.setattr(evaluate_final_holdout, "_load_observations", guarded)
    with pytest.raises(ValueError, match="legacy_preexisting_2023_2024_final_holdout"):
        evaluate_final_holdout.main(_argv(paths))

    registry = json.loads(paths["consumption"].read_text(encoding="utf-8"))
    assert registry["schema_version"] == "forecast_final_holdout_consumption_v1"
    assert registry["policy_blocks"][0]["source"] == "legacy_preexisting_2023_2024_final_holdout"
