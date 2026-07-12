from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from backtesting.historical_dataset import load_historical_feature_snapshots


def _snapshot(*, available_at: str = "2024-01-01T00:00:00+00:00") -> dict[str, object]:
    return {
        "as_of": "2024-01-02T00:00:00+00:00",
        "symbol": "nvda",
        "values": {
            "price": {"value": 100.0, "available_at": available_at, "freshness": "last_close"},
            "revenue_growth_yoy_pct": {"value": 35.0, "available_at": available_at, "freshness": "quarterly"},
        },
    }


def test_loader_preserves_point_in_time_metric_availability(tmp_path) -> None:
    path = tmp_path / "snapshots.jsonl"
    path.write_text(json.dumps(_snapshot()) + "\n", encoding="utf-8")

    snapshots = load_historical_feature_snapshots(path)

    assert snapshots[0].symbol == "NVDA"
    assert snapshots[0].to_screener_metrics().get_float("revenue_growth_yoy_pct") == 35.0
    assert snapshots[0].values["price"].available_at == datetime(2024, 1, 1, tzinfo=timezone.utc)


def test_loader_rejects_metrics_that_were_not_known_at_snapshot_time(tmp_path) -> None:
    path = tmp_path / "snapshots.jsonl"
    path.write_text(json.dumps(_snapshot(available_at="2024-01-03T00:00:00+00:00")) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="metrics unavailable at snapshot time"):
        load_historical_feature_snapshots(path)
