from datetime import date, timedelta

from backtesting.forecast import ForecastObservation, fit_forecast_model
from backtesting.forecast_diagnostics import build_forecast_calibration_diagnostics
from backtesting.walk_forward import WalkForwardSettings


def _observations() -> list[ForecastObservation]:
    start = date(2020, 1, 1)
    return [
        ForecastObservation(
            as_of=start + timedelta(days=index),
            symbol=f"S{index % 6}",
            signal_score=(index % 100) + 0.5,
            forward_return_3m=0.3 if index % 100 >= 70 else -0.05,
            max_drawdown_3m=-0.05 if index % 100 >= 70 else -0.3,
        )
        for index in range(720)
    ]


def test_calibration_diagnostics_match_model_aggregate_metrics() -> None:
    model = fit_forecast_model(
        _observations(),
        walk_forward=WalkForwardSettings(training_sessions=60, validation_sessions=10, test_sessions=20, step_sessions=20),
    )

    diagnostics = build_forecast_calibration_diagnostics(model)

    assert diagnostics["out_of_sample"]["count"] == model.metrics.out_of_sample_count
    assert diagnostics["out_of_sample"]["upside_brier_score"] == model.metrics.upside_brier_score
    assert diagnostics["out_of_sample"]["downside_brier_score"] == model.metrics.downside_brier_score
    assert len(diagnostics["folds"]) == model.metrics.fold_count
    assert sum(bucket["count"] for bucket in diagnostics["score_buckets"]) == model.metrics.out_of_sample_count
