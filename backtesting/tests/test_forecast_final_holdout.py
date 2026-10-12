from __future__ import annotations

from datetime import date, timedelta

import pytest

from backtesting.forecast import ForecastObservation
from backtesting.forecast_final_holdout import fit_frozen_continuous_feature_artifact, score_final_holdout
from backtesting.walk_forward import WalkForwardSettings


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
def small_feature_model(monkeypatch: pytest.MonkeyPatch) -> None:
    from backtesting import forecast_feature_model

    config = forecast_feature_model.load_forecast_feature_config().copy()
    config["logistic_regression"] = {"regularization_candidates": [0.1, 1.0], "minimum_training_observations": 30, "max_iterations": 200}
    config["probability_shrinkage"] = {
        "feature_model_weights": [0.0, 0.5, 1.0],
        "prior_sources": ["global_flat", "regime_flat"],
    }
    monkeypatch.setattr(forecast_feature_model, "load_forecast_feature_config", lambda: config)


def _artifact_and_holdout():
    selection_start = date(2020, 1, 1)
    final_start = date(2023, 1, 3)
    selection = [_observation(selection_start + timedelta(days=index), index) for index in range(180)]
    final_holdout = [_observation(final_start + timedelta(days=index), index + 1) for index in range(90)]
    artifact = fit_frozen_continuous_feature_artifact(
        selection,
        holdout_start=date(2023, 1, 1),
        point_in_time_certified=False,
        walk_forward=WalkForwardSettings(training_sessions=40, validation_sessions=20, test_sessions=20, step_sessions=20),
    )
    return artifact, final_holdout


def test_final_holdout_outcomes_cannot_change_the_frozen_artifact_or_predictions() -> None:
    artifact, final_holdout = _artifact_and_holdout()
    first = score_final_holdout(artifact, final_holdout, bootstrap_samples=20)
    altered = [
        item.model_copy(update={"forward_return_3m": -0.5, "max_drawdown_3m": -0.5})
        for item in final_holdout
    ]
    second = score_final_holdout(artifact, altered, bootstrap_samples=20)

    assert first["trained_artifact"] == second["trained_artifact"]
    assert first["calibration"]["upside"]["mean_prediction"] == second["calibration"]["upside"]["mean_prediction"]
    assert first["calibration"]["downside"]["mean_prediction"] == second["calibration"]["downside"]["mean_prediction"]
    assert first["out_of_sample_metrics"]["upside_brier_score"] != second["out_of_sample_metrics"]["upside_brier_score"]


def test_final_holdout_rejects_selection_rows_and_stays_fail_closed() -> None:
    artifact, final_holdout = _artifact_and_holdout()
    report = score_final_holdout(artifact, final_holdout, bootstrap_samples=20)

    assert report["calibration_status"] == "unavailable"
    assert report["numeric_forecast_status"] == "unavailable"
    with pytest.raises(ValueError, match="selection-period"):
        score_final_holdout(artifact, [_observation(date(2022, 12, 30), 1)], bootstrap_samples=20)


def test_final_holdout_rejects_feature_schema_mismatch() -> None:
    artifact, final_holdout = _artifact_and_holdout()
    mismatched = final_holdout[0].model_copy(update={"feature_schema_version": "bucket_v1"})

    with pytest.raises(ValueError, match="label or feature schema"):
        score_final_holdout(artifact, [mismatched, *final_holdout[1:]], bootstrap_samples=20)
