from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from analyst_service.core.persistence import PersistedAnalysis, load_persisted_analyses


TRADING_DAY_WINDOWS = {"1D": 1, "1W": 5, "1M": 21, "3M": 63}
HORIZON_TO_WINDOW = {"1D": "1D", "1W": "1W", "2-4W": "1M", "3-6M": "3M"}
PriceLoader = Callable[[str, date, date], pd.Series | pd.DataFrame]


@dataclass(frozen=True)
class EvaluatedAnalysis:
    record_id: int
    symbol: str
    direction: str
    entry_assessment: str | None
    target_window: str
    forward_returns: dict[str, float]
    benchmark_relative_returns: dict[str, float]
    max_drawdown: float | None
    realized_volatility: float | None
    risk_adjusted_return: float | None
    hit: bool | None
    skipped_reason: str | None = None


@dataclass(frozen=True)
class PerformanceSummary:
    evaluated_count: int
    decision_count: int
    hit_rate: float | None
    average_forward_return: float | None
    average_benchmark_relative_return: float | None
    average_max_drawdown: float | None
    average_risk_adjusted_return: float | None


@dataclass(frozen=True)
class EvaluationReport:
    results: list[EvaluatedAnalysis]
    by_strategy: dict[str, PerformanceSummary]
    by_entry_assessment: dict[str, PerformanceSummary]
    advisory: list[str]


def evaluate_store(
    path: Path | None = None,
    *,
    price_loader: PriceLoader | None = None,
    benchmark_symbol: str = "SPY",
) -> EvaluationReport:
    return evaluate_records(
        load_persisted_analyses(path),
        price_loader=price_loader or fetch_adjusted_close_history,
        benchmark_symbol=benchmark_symbol,
    )


def evaluate_records(
    records: Iterable[PersistedAnalysis],
    *,
    price_loader: PriceLoader,
    benchmark_symbol: str = "SPY",
) -> EvaluationReport:
    results: list[EvaluatedAnalysis] = []
    for record in records:
        results.append(_evaluate_record(record, price_loader, benchmark_symbol))

    by_strategy = {"analysis": _summarize(results)}
    entry_assessments = sorted({result.entry_assessment for result in results if result.entry_assessment})
    by_entry_assessment = {
        assessment: _summarize([result for result in results if result.entry_assessment == assessment])
        for assessment in entry_assessments
    }
    return EvaluationReport(
        results=results,
        by_strategy=by_strategy,
        by_entry_assessment=by_entry_assessment,
        advisory=_advisory(by_strategy["analysis"]),
    )


def fetch_adjusted_close_history(symbol: str, start: date, end: date) -> pd.Series:
    import yfinance as yf

    history = yf.Ticker(symbol).history(
        start=start.isoformat(),
        end=(end + timedelta(days=1)).isoformat(),
        auto_adjust=True,
    )
    if "Close" not in history:
        return pd.Series(dtype=float)
    return history["Close"]


def _evaluate_record(record: PersistedAnalysis, price_loader: PriceLoader, benchmark_symbol: str) -> EvaluatedAnalysis:
    start = record.generated_at.date()
    end = start + timedelta(days=120)
    prices = _normalize_prices(price_loader(record.symbol, start, end))
    if prices.empty:
        return _skipped(record, "price history unavailable")

    entry_position = prices.index.searchsorted(pd.Timestamp(start))
    if entry_position >= len(prices):
        return _skipped(record, "price history starts after the signal")

    benchmark_prices = _normalize_prices(price_loader(benchmark_symbol, start, end))
    benchmark_position = benchmark_prices.index.searchsorted(pd.Timestamp(start))
    forward_returns = _forward_returns(prices, entry_position)
    benchmark_returns = (
        _forward_returns(benchmark_prices, benchmark_position) if benchmark_position < len(benchmark_prices) else {}
    )
    benchmark_relative_returns = {
        window: round(value - benchmark_returns[window], 6)
        for window, value in forward_returns.items()
        if window in benchmark_returns
    }
    target_window = HORIZON_TO_WINDOW.get(record.horizon, "1M")
    target_return = forward_returns.get(target_window)
    if target_return is None:
        return _skipped(record, f"insufficient history for {target_window}", forward_returns, benchmark_relative_returns)

    max_window_position = min(entry_position + TRADING_DAY_WINDOWS["3M"], len(prices) - 1)
    path = prices.iloc[entry_position : max_window_position + 1]
    entry_price = float(path.iloc[0])
    max_drawdown = round(float(path.min() / entry_price - 1), 6)
    returns = path.pct_change().dropna()
    realized_volatility = round(float(returns.std(ddof=0)), 6) if not returns.empty else None
    risk_adjusted_return = (
        round(target_return / realized_volatility, 6) if realized_volatility and realized_volatility > 0 else None
    )
    hit = _hit(record.direction, target_return)
    return EvaluatedAnalysis(
        record_id=record.id,
        symbol=record.symbol,
        direction=record.direction,
        entry_assessment=record.entry_assessment,
        target_window=target_window,
        forward_returns=forward_returns,
        benchmark_relative_returns=benchmark_relative_returns,
        max_drawdown=max_drawdown,
        realized_volatility=realized_volatility,
        risk_adjusted_return=risk_adjusted_return,
        hit=hit,
    )


def _normalize_prices(values: pd.Series | pd.DataFrame) -> pd.Series:
    if isinstance(values, pd.DataFrame):
        close_column = "Close" if "Close" in values else "close" if "close" in values else None
        values = values[close_column] if close_column else pd.Series(dtype=float)
    series = pd.to_numeric(values, errors="coerce").dropna().astype(float)
    if series.empty:
        return series
    index = pd.DatetimeIndex(series.index)
    if index.tz is not None:
        index = index.tz_localize(None)
    series.index = index.normalize()
    return series[~series.index.duplicated(keep="last")].sort_index()


def _forward_returns(prices: pd.Series, entry_position: int) -> dict[str, float]:
    entry_price = float(prices.iloc[entry_position])
    returns: dict[str, float] = {}
    for window, sessions in TRADING_DAY_WINDOWS.items():
        exit_position = entry_position + sessions
        if exit_position < len(prices):
            returns[window] = round(float(prices.iloc[exit_position] / entry_price - 1), 6)
    return returns


def _hit(direction: str, forward_return: float) -> bool | None:
    if direction == "BUY":
        return forward_return > 0
    if direction == "SELL":
        return forward_return < 0
    return None


def _skipped(
    record: PersistedAnalysis,
    reason: str,
    forward_returns: dict[str, float] | None = None,
    benchmark_relative_returns: dict[str, float] | None = None,
) -> EvaluatedAnalysis:
    return EvaluatedAnalysis(
        record_id=record.id,
        symbol=record.symbol,
        direction=record.direction,
        entry_assessment=record.entry_assessment,
        target_window=HORIZON_TO_WINDOW.get(record.horizon, "1M"),
        forward_returns=forward_returns or {},
        benchmark_relative_returns=benchmark_relative_returns or {},
        max_drawdown=None,
        realized_volatility=None,
        risk_adjusted_return=None,
        hit=None,
        skipped_reason=reason,
    )


def _summarize(results: list[EvaluatedAnalysis]) -> PerformanceSummary:
    evaluated = [result for result in results if result.skipped_reason is None]
    decisions = [result for result in evaluated if result.hit is not None]
    primary_returns = [
        result.forward_returns.get(result.target_window)
        for result in evaluated
        if result.forward_returns.get(result.target_window) is not None
    ]
    benchmark_relative_returns = [
        result.benchmark_relative_returns.get(result.target_window)
        for result in evaluated
        if result.benchmark_relative_returns.get(result.target_window) is not None
    ]
    drawdowns = [result.max_drawdown for result in evaluated if result.max_drawdown is not None]
    risk_adjusted_returns = [
        result.risk_adjusted_return for result in evaluated if result.risk_adjusted_return is not None
    ]
    return PerformanceSummary(
        evaluated_count=len(evaluated),
        decision_count=len(decisions),
        hit_rate=round(sum(result.hit for result in decisions) / len(decisions), 6) if decisions else None,
        average_forward_return=_mean(primary_returns),
        average_benchmark_relative_return=_mean(benchmark_relative_returns),
        average_max_drawdown=_mean(drawdowns),
        average_risk_adjusted_return=_mean(risk_adjusted_returns),
    )


def _mean(values: list[float | None]) -> float | None:
    valid = [value for value in values if value is not None]
    return round(sum(valid) / len(valid), 6) if valid else None


def _advisory(summary: PerformanceSummary) -> list[str]:
    if summary.evaluated_count < 20:
        return [
            f"Only {summary.evaluated_count} recommendations have enough forward history; do not tune live weights yet.",
            "Use this report to inspect hypotheses and collect more out-of-sample observations.",
        ]
    return [
        "Review results by entry assessment before proposing any weight change.",
        "Weight changes remain advisory until separately reviewed and backtested out of sample.",
    ]
