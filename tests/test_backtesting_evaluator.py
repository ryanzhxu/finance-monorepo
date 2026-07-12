from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from analyst_service.core.persistence import PersistedAnalysis
from backtesting.evaluator import evaluate_records


def _record(*, direction: str = "BUY", horizon: str = "2-4W") -> PersistedAnalysis:
    return PersistedAnalysis(
        id=1,
        symbol="NVDA",
        generated_at=datetime(2025, 1, 2, tzinfo=timezone.utc),
        horizon=horizon,
        direction=direction,
        confidence=0.8,
        weighted_score=0.8,
        data_quality_score=90,
        entry_assessment="buy_now",
        current_price=100.0,
        payload={},
    )


def _price_loader(symbol, start, end):
    index = pd.bdate_range("2025-01-02", periods=70)
    if symbol == "SPY":
        return pd.Series([100 + index_value * 0.1 for index_value in range(len(index))], index=index)
    return pd.Series([100 + index_value for index_value in range(len(index))], index=index)


def test_evaluator_computes_forward_returns_and_benchmark_relative_metrics() -> None:
    report = evaluate_records([_record()], price_loader=_price_loader)

    result = report.results[0]
    summary = report.by_strategy["analysis"]
    assert result.forward_returns["1D"] == 0.01
    assert result.forward_returns["1W"] == 0.05
    assert result.forward_returns["1M"] == 0.21
    assert result.benchmark_relative_returns["1M"] == 0.189
    assert result.max_drawdown == 0.0
    assert result.hit is True
    assert summary.evaluated_count == 1
    assert summary.hit_rate == 1.0
    assert summary.average_forward_return == 0.21
    assert report.by_entry_assessment["buy_now"].evaluated_count == 1
    assert "do not tune live weights yet" in report.advisory[0]


def test_evaluator_marks_records_without_enough_history_as_skipped() -> None:
    def short_loader(symbol, start, end):
        return pd.Series([100, 101, 102], index=pd.bdate_range("2025-01-02", periods=3))

    report = evaluate_records([_record()], price_loader=short_loader)

    assert report.results[0].skipped_reason == "insufficient history for 1M"
    assert report.by_strategy["analysis"].evaluated_count == 0
