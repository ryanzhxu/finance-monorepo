from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, field_validator, model_validator

from shared.enums import Freshness

from screener_service.core.fundamentals_bulk import MetricValue, ScreenerMetrics


class HistoricalMetric(BaseModel):
    value: float | str | None = None
    available_at: datetime | None = None
    freshness: Freshness = Freshness.QUARTERLY


class HistoricalFeatureSnapshot(BaseModel):
    as_of: datetime
    symbol: str
    values: dict[str, HistoricalMetric]

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("symbol is required")
        return normalized

    @model_validator(mode="after")
    def validate_feature_availability(self) -> HistoricalFeatureSnapshot:
        future_metrics = [key for key, metric in self.values.items() if metric.available_at and metric.available_at > self.as_of]
        if future_metrics:
            raise ValueError(f"metrics unavailable at snapshot time: {', '.join(sorted(future_metrics))}")
        return self

    def to_screener_metrics(self) -> ScreenerMetrics:
        return ScreenerMetrics(
            symbol=self.symbol,
            values={
                key: MetricValue(value=metric.value, freshness=metric.freshness, as_of=metric.available_at)
                for key, metric in self.values.items()
            },
        )


def load_historical_feature_snapshots(path: Path) -> list[HistoricalFeatureSnapshot]:
    snapshots: list[HistoricalFeatureSnapshot] = []
    seen: set[tuple[datetime, str]] = set()
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            snapshot = HistoricalFeatureSnapshot.model_validate(json.loads(line))
        except (ValueError, TypeError) as exc:
            raise ValueError(f"invalid historical snapshot at line {line_number}: {exc}") from exc
        key = (snapshot.as_of, snapshot.symbol)
        if key in seen:
            raise ValueError(f"duplicate historical snapshot at line {line_number}: {snapshot.symbol} {snapshot.as_of.isoformat()}")
        seen.add(key)
        snapshots.append(snapshot)
    return sorted(snapshots, key=lambda snapshot: (snapshot.as_of, snapshot.symbol))
