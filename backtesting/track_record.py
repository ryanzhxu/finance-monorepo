"""Did our past calls actually work?

Vincent asked for this twice — a history in the dashboard, and a backtest over
it (2026-07-24, 2026-07-27). It is also the answer to his condition for acting
on any recommendation at all (2026-07-10): he has to believe it, and a call
with no track record cannot be believed.

Everything underneath already existed. `/analyze` has been persisting to SQLite
since before this module, and `backtesting/evaluator.py` already scores those
records against realized forward returns. This is the layer that makes it
reachable, plus the one thing the evaluator did not have: hit rate split by the
confidence the engine claimed at the time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from analyst_service.core.persistence import PersistedAnalysis, load_persisted_analyses
from backtesting.evaluator import (
    EvaluatedAnalysis,
    PriceLoader,
    evaluate_records,
    fetch_adjusted_close_history,
)
from backtesting.price_cache import BatchPriceLoader


# Fixed buckets. They exist to answer one question: when the engine says it is
# confident, is it right more often?
CONFIDENCE_BUCKETS: tuple[tuple[str, float, float], ...] = (
    ("0.0-0.5", 0.0, 0.5),
    ("0.5-0.65", 0.5, 0.65),
    ("0.65-0.8", 0.65, 0.8),
    ("0.8-1.0", 0.8, 1.0001),
)


@dataclass(frozen=True)
class TrackRecordEntry:
    symbol: str
    generated_at: datetime
    direction: str
    confidence: float
    entry_assessment: str | None
    price_at_call: float | None
    target_window: str
    forward_returns: dict[str, float]
    benchmark_relative_returns: dict[str, float]
    max_drawdown: float | None
    hit: bool | None
    skipped_reason: str | None


@dataclass(frozen=True)
class PerformanceBucket:
    label: str
    evaluated_count: int
    decision_count: int
    hit_rate: float | None
    average_forward_return: float | None


@dataclass(frozen=True)
class PerformanceReport:
    evaluated_count: int
    decision_count: int
    hit_rate: float | None
    average_forward_return: float | None
    average_benchmark_relative_return: float | None
    by_direction: list[PerformanceBucket] = field(default_factory=list)
    by_confidence: list[PerformanceBucket] = field(default_factory=list)
    by_entry_assessment: list[PerformanceBucket] = field(default_factory=list)
    advisory: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class StoreCoverage:
    record_count: int
    distinct_symbols: int
    earliest: datetime | None
    latest: datetime | None


def store_coverage(*, path: Path | None = None) -> StoreCoverage:
    """How much history exists. Deliberately free of provider calls, so the UI
    can render an honest empty state before spending anything."""
    records = load_persisted_analyses(path)
    if not records:
        return StoreCoverage(record_count=0, distinct_symbols=0, earliest=None, latest=None)
    timestamps = [record.generated_at for record in records]
    return StoreCoverage(
        record_count=len(records),
        distinct_symbols=len({record.symbol.upper() for record in records}),
        earliest=min(timestamps),
        latest=max(timestamps),
    )


def _evaluate(
    records: list[PersistedAnalysis],
    price_loader: PriceLoader | None,
    benchmark_symbol: str,
) -> list[EvaluatedAnalysis]:
    if not records:
        return []
    loader = BatchPriceLoader(
        price_loader or fetch_adjusted_close_history,
        records,
        benchmark_symbol=benchmark_symbol,
    )
    return evaluate_records(records, price_loader=loader, benchmark_symbol=benchmark_symbol).results


def symbol_timeline(
    symbol: str,
    *,
    path: Path | None = None,
    price_loader: PriceLoader | None = None,
    benchmark_symbol: str = "SPY",
    limit: int | None = None,
) -> list[TrackRecordEntry]:
    """Every past call for one symbol, newest first, with what happened after.

    This is Vincent's META test: what did we say, at what price, and where did
    the price go.
    """
    records = load_persisted_analyses(path, symbol=symbol, limit=limit)
    if not records:
        return []

    by_id = {record.id: record for record in records}
    results = _evaluate(records, price_loader, benchmark_symbol)
    entries = [
        TrackRecordEntry(
            symbol=result.symbol,
            generated_at=by_id[result.record_id].generated_at,
            direction=result.direction,
            confidence=by_id[result.record_id].confidence,
            entry_assessment=result.entry_assessment,
            price_at_call=by_id[result.record_id].current_price,
            target_window=result.target_window,
            forward_returns=result.forward_returns,
            benchmark_relative_returns=result.benchmark_relative_returns,
            max_drawdown=result.max_drawdown,
            hit=result.hit,
            skipped_reason=result.skipped_reason,
        )
        for result in results
        if result.record_id in by_id
    ]
    return sorted(entries, key=lambda entry: entry.generated_at, reverse=True)


def _bucket(label: str, results: list[EvaluatedAnalysis]) -> PerformanceBucket:
    evaluated = [result for result in results if result.skipped_reason is None]
    decisions = [result for result in evaluated if result.hit is not None]
    returns = [
        result.forward_returns.get(result.target_window)
        for result in evaluated
        if result.forward_returns.get(result.target_window) is not None
    ]
    return PerformanceBucket(
        label=label,
        evaluated_count=len(evaluated),
        decision_count=len(decisions),
        hit_rate=round(sum(1 for r in decisions if r.hit) / len(decisions), 4) if decisions else None,
        average_forward_return=round(sum(returns) / len(returns), 6) if returns else None,
    )


def performance_report(
    *,
    path: Path | None = None,
    symbol: str | None = None,
    since: datetime | None = None,
    price_loader: PriceLoader | None = None,
    benchmark_symbol: str = "SPY",
) -> PerformanceReport:
    """Aggregate hit rate, overall and split by direction, confidence and entry."""
    records = load_persisted_analyses(path, symbol=symbol, since=since)
    results = _evaluate(records, price_loader, benchmark_symbol)
    confidence_by_id = {record.id: record.confidence for record in records}

    overall = _bucket("all", results)
    evaluated = [result for result in results if result.skipped_reason is None]
    benchmark_relative = [
        result.benchmark_relative_returns.get(result.target_window)
        for result in evaluated
        if result.benchmark_relative_returns.get(result.target_window) is not None
    ]

    by_direction = [
        _bucket(direction, [r for r in results if r.direction == direction])
        for direction in sorted({result.direction for result in results})
    ]
    by_confidence = [
        _bucket(
            label,
            [r for r in results if low <= confidence_by_id.get(r.record_id, 0.0) < high],
        )
        for label, low, high in CONFIDENCE_BUCKETS
    ]
    by_entry = [
        _bucket(assessment, [r for r in results if r.entry_assessment == assessment])
        for assessment in sorted({r.entry_assessment for r in results if r.entry_assessment})
    ]

    return PerformanceReport(
        evaluated_count=overall.evaluated_count,
        decision_count=overall.decision_count,
        hit_rate=overall.hit_rate,
        average_forward_return=overall.average_forward_return,
        average_benchmark_relative_return=(
            round(sum(benchmark_relative) / len(benchmark_relative), 6) if benchmark_relative else None
        ),
        by_direction=by_direction,
        by_confidence=by_confidence,
        by_entry_assessment=by_entry,
        advisory=_advisory(overall.evaluated_count),
    )


def _advisory(evaluated_count: int) -> list[str]:
    """Say plainly when the sample is too thin to mean anything.

    Mirrors the evaluator's own threshold. A hit rate over four records is a
    coin flip with extra steps, and must not read as a verdict.
    """
    if evaluated_count == 0:
        return ["No recommendations have enough forward history yet; nothing here is measurable."]
    if evaluated_count < 20:
        return [
            f"Only {evaluated_count} recommendations have enough forward history; treat every rate here as provisional.",
            "Do not tune signal weights on this sample.",
        ]
    return [
        "Review results by entry assessment before proposing any weight change.",
        "Weight changes remain advisory until separately reviewed and backtested out of sample.",
    ]
