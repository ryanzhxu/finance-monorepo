from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ForecastDataProvenance(BaseModel):
    """Documents whether a historical-price run is safe to promote to forecasts."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["forecast_price_provenance_v1"] = "forecast_price_provenance_v1"
    source: Literal["yfinance"] = "yfinance"
    adjustment_mode: Literal["auto_adjusted_current_view"] = "auto_adjusted_current_view"
    point_in_time_certified: bool = False
    corporate_actions_available_as_of: bool = False
    universe_membership_point_in_time: bool = False
    generated_at: datetime
    requested_start: date
    requested_end: date
    symbols_requested: int
    symbols_with_observations: int
    snapshot_step_sessions: int = 1
    feature_schema_version: str = "bucket_v1"
    benchmark_symbols: list[str] = Field(default_factory=list)
    run_id: str | None = None
    note: str = (
        "Yahoo auto-adjusted history is a current view and does not prove historical corporate-action "
        "availability or historical universe membership. It is experimental only."
    )


def build_yfinance_price_provenance(
    *,
    requested_start: date,
    requested_end: date,
    symbols_requested: int,
    symbols_with_observations: int,
    run_id: str | None,
    snapshot_step_sessions: int = 1,
    feature_schema_version: str = "bucket_v1",
    benchmark_symbols: list[str] | None = None,
) -> ForecastDataProvenance:
    return ForecastDataProvenance(
        generated_at=datetime.now(timezone.utc),
        requested_start=requested_start,
        requested_end=requested_end,
        symbols_requested=symbols_requested,
        symbols_with_observations=symbols_with_observations,
        run_id=run_id,
        snapshot_step_sessions=snapshot_step_sessions,
        feature_schema_version=feature_schema_version,
        benchmark_symbols=benchmark_symbols or [],
    )


def load_forecast_data_provenance(path: Path) -> ForecastDataProvenance:
    return ForecastDataProvenance.model_validate_json(path.read_text(encoding="utf-8"))
