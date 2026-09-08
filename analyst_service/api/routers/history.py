"""Track-record endpoints: what we said before, and whether it worked.

`/history/coverage` deliberately makes no provider calls, so a client can find
out whether there is anything to show before spending a rate-limited request.
The other two evaluate stored analyses against realized prices through the
batched loader, which costs one provider call per distinct symbol.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Query

from shared.models import (
    PerformanceBucketModel,
    TrackRecordCoverageResponse,
    TrackRecordEntryModel,
    TrackRecordPerformanceResponse,
    TrackRecordTimelineResponse,
)

from backtesting.track_record import performance_report, store_coverage, symbol_timeline


router = APIRouter()


def _bucket(bucket) -> PerformanceBucketModel:
    return PerformanceBucketModel(
        label=bucket.label,
        evaluated_count=bucket.evaluated_count,
        decision_count=bucket.decision_count,
        hit_rate=bucket.hit_rate,
        average_forward_return=bucket.average_forward_return,
    )


@router.get("/history/coverage", response_model=TrackRecordCoverageResponse)
def history_coverage() -> TrackRecordCoverageResponse:
    coverage = store_coverage()
    return TrackRecordCoverageResponse(
        record_count=coverage.record_count,
        distinct_symbols=coverage.distinct_symbols,
        earliest=coverage.earliest,
        latest=coverage.latest,
    )


@router.get("/history/performance", response_model=TrackRecordPerformanceResponse)
def history_performance(
    symbol: str | None = Query(default=None),
    since: datetime | None = Query(default=None),
) -> TrackRecordPerformanceResponse:
    report = performance_report(symbol=symbol, since=since)
    return TrackRecordPerformanceResponse(
        generated_at=datetime.now(timezone.utc),
        evaluated_count=report.evaluated_count,
        decision_count=report.decision_count,
        hit_rate=report.hit_rate,
        average_forward_return=report.average_forward_return,
        average_benchmark_relative_return=report.average_benchmark_relative_return,
        by_direction=[_bucket(b) for b in report.by_direction],
        by_confidence=[_bucket(b) for b in report.by_confidence],
        by_entry_assessment=[_bucket(b) for b in report.by_entry_assessment],
        advisory=report.advisory,
    )


@router.get("/history/{symbol}", response_model=TrackRecordTimelineResponse)
def history_symbol(
    symbol: str,
    limit: int | None = Query(default=50, ge=1, le=500),
) -> TrackRecordTimelineResponse:
    # An unknown symbol is an empty timeline, not a 404 — "we have never
    # analyzed this" is a legitimate answer, not an error.
    entries = symbol_timeline(symbol.strip().upper(), limit=limit)
    return TrackRecordTimelineResponse(
        symbol=symbol.strip().upper(),
        generated_at=datetime.now(timezone.utc),
        entries=[
            TrackRecordEntryModel(
                symbol=entry.symbol,
                generated_at=entry.generated_at,
                direction=entry.direction,
                confidence=entry.confidence,
                entry_assessment=entry.entry_assessment,
                price_at_call=entry.price_at_call,
                target_window=entry.target_window,
                forward_returns=entry.forward_returns,
                benchmark_relative_returns=entry.benchmark_relative_returns,
                max_drawdown=entry.max_drawdown,
                hit=entry.hit,
                skipped_reason=entry.skipped_reason,
            )
            for entry in entries
        ],
    )
