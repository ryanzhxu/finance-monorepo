from __future__ import annotations

from datetime import date, timedelta

import pytest

from backtesting.forecast import ForecastObservation
from backtesting.forecast_feature_model import build_continuous_feature_report, fit_continuous_feature_model
from backtesting.sec_fundamental_features import COMBINED_FEATURE_SCHEMA
from backtesting.walk_forward import WalkForwardSettings


def _observations(count: int = 260) -> list[ForecastObservation]:
    start = date(2020, 1, 1)
    rows: list[ForecastObservation] = []
    for index in range(count):
        feature = float((index % 10) / 10)
        upside = 0.30 if feature >= 0.5 else -0.06
        downside = -0.08 if feature >= 0.5 else -0.30
        rows.append(
            ForecastObservation(
                as_of=start + timedelta(days=index),
                symbol=f"S{index % 7}",
                signal_score=80 if feature >= 0.5 else 20,
                forward_return_3m=upside,
                max_drawdown_3m=downside,
                label_version="next_open_low_v2",
                feature_schema_version="continuous_regime_v1",
                feature_values={"feature": feature, "market": 1.0, "regime_risk_on": float(index % 3 == 0)},
                market_regime=("risk_on" if index % 3 == 0 else "neutral"),
            )
        )
    return rows


@pytest.fixture(autouse=True)
def small_feature_model(monkeypatch: pytest.MonkeyPatch) -> None:
    from backtesting import forecast_feature_model

    config = forecast_feature_model.load_forecast_feature_config().copy()
    config["logistic_regression"] = {"regularization_candidates": [0.1, 1.0], "minimum_training_observations": 30, "max_iterations": 200}
    config["probability_shrinkage"] = {
        "feature_model_weights": [0.0, 0.5, 1.0],
        "prior_sources": ["global_flat", "regime_flat"],
    }
    monkeypatch.setattr(forecast_feature_model, "load_forecast_feature_config", lambda: config)


def test_feature_model_is_fail_closed_without_certified_provenance() -> None:
    model = fit_continuous_feature_model(
        _observations(),
        walk_forward=WalkForwardSettings(training_sessions=40, validation_sessions=20, test_sessions=20, step_sessions=20),
        point_in_time_certified=False,
    )

    report = build_continuous_feature_report(model)
    assert model.metrics.out_of_sample_count > 100
    assert model.status == "unavailable"
    assert report["calibration_status"] == "unavailable"
    assert report["feature_schema_version"] == "continuous_regime_v1"
    assert report["out_of_sample_metrics"] == model.diagnostics["aggregate_metrics"]


def test_feature_model_rejects_mixed_label_or_feature_schemas() -> None:
    mixed_labels = _observations(100)
    mixed_labels[0] = mixed_labels[0].model_copy(update={"label_version": "close_v1"})
    with pytest.raises(ValueError, match="one label version"):
        fit_continuous_feature_model(mixed_labels)

    mixed_features = _observations(100)
    mixed_features[0] = mixed_features[0].model_copy(update={"feature_schema_version": "bucket_v1"})
    with pytest.raises(ValueError, match="continuous feature model requires"):
        fit_continuous_feature_model(mixed_features)


def test_feature_model_accepts_versioned_sec_fundamental_schema() -> None:
    observations = [
        item.model_copy(
            update={
                "feature_schema_version": COMBINED_FEATURE_SCHEMA,
                "feature_values": {**item.feature_values, "sec_revenue_yoy": 0.12},
            }
        )
        for item in _observations()
    ]

    model = fit_continuous_feature_model(
        observations,
        walk_forward=WalkForwardSettings(training_sessions=40, validation_sessions=20, test_sessions=20, step_sessions=20),
    )

    report = build_continuous_feature_report(model)
    assert model.feature_schema_version == COMBINED_FEATURE_SCHEMA
    assert model.diagnostics["feature_schema_version"] == COMBINED_FEATURE_SCHEMA
    assert report["feature_schema_version"] == COMBINED_FEATURE_SCHEMA
    assert report["model_version"] == f"forecast_{COMBINED_FEATURE_SCHEMA}"


def test_feature_subset_excludes_only_configured_payload_columns() -> None:
    model = fit_continuous_feature_model(
        _observations(),
        walk_forward=WalkForwardSettings(training_sessions=40, validation_sessions=20, test_sessions=20, step_sessions=20),
    )

    report = build_continuous_feature_report(model)
    assert report["feature_payload_names"] == ["feature", "market", "regime_risk_on"]
    assert report["feature_names"] == ["feature", "market"]
    assert report["model_version"] == "forecast_continuous_regime_v3_target_calibration_v1"


def test_feature_subset_rejects_malformed_config(monkeypatch: pytest.MonkeyPatch) -> None:
    from backtesting import forecast_feature_model

    config = forecast_feature_model.load_forecast_feature_config().copy()
    config["feature_selection"] = {"excluded_features": "regime_risk_on"}
    monkeypatch.setattr(forecast_feature_model, "load_forecast_feature_config", lambda: config)

    with pytest.raises(ValueError, match="must be a list"):
        fit_continuous_feature_model(_observations())


def test_validation_selection_does_not_read_test_outcomes() -> None:
    observations = _observations(90)
    settings = WalkForwardSettings(training_sessions=40, validation_sessions=20, test_sessions=20, step_sessions=20)
    first = fit_continuous_feature_model(observations, walk_forward=settings, point_in_time_certified=False)
    altered = list(observations)
    for index in range(70, 90):
        altered[index] = altered[index].model_copy(update={"forward_return_3m": -0.5, "max_drawdown_3m": -0.5})
    second = fit_continuous_feature_model(altered, walk_forward=settings, point_in_time_certified=False)

    assert first.diagnostics["folds"][0]["upside"]["selected_regularization"] == second.diagnostics["folds"][0]["upside"]["selected_regularization"]
    assert first.diagnostics["folds"][0]["downside"]["selected_regularization"] == second.diagnostics["folds"][0]["downside"]["selected_regularization"]
    assert first.diagnostics["folds"][0]["upside"]["selected_feature_model_weight"] == second.diagnostics["folds"][0]["upside"]["selected_feature_model_weight"]
    assert first.diagnostics["folds"][0]["downside"]["selected_feature_model_weight"] == second.diagnostics["folds"][0]["downside"]["selected_feature_model_weight"]
    assert first.diagnostics["folds"][0]["upside"]["selected_prior_source"] == second.diagnostics["folds"][0]["upside"]["selected_prior_source"]
    assert first.diagnostics["folds"][0]["downside"]["selected_prior_source"] == second.diagnostics["folds"][0]["downside"]["selected_prior_source"]
    assert first.diagnostics["folds"][0]["upside"]["selected_temperature"] == second.diagnostics["folds"][0]["upside"]["selected_temperature"]
    assert first.diagnostics["folds"][0]["downside"]["selected_regime_calibrations"] == second.diagnostics["folds"][0]["downside"]["selected_regime_calibrations"]
