from __future__ import annotations

from datetime import date

from backtesting.forecast import CalibratedForecastModel, ForecastContract


def build_forecast_run_report(
    model: CalibratedForecastModel,
    *,
    as_of: date,
    signal_score: float = 50.0,
) -> ForecastContract:
    """Return the auditable model-run contract used by downstream consumers.

    The score is only a report probe. It is never used as a candidate forecast;
    candidate-level scores must be supplied by deterministic feature code.
    """

    return model.predict(
        mode="upside_discovery",
        as_of=as_of,
        signal_score=signal_score,
    )
