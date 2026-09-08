"""Batched price loading, so scoring past calls can be served over HTTP.

``evaluate_records`` calls its price loader twice per record — once for the
symbol, once for the benchmark. A symbol analyzed forty times therefore costs
eighty provider calls. That is fine for an offline report and unacceptable for
a request handler backed by a rate-limited provider.

``BatchPriceLoader`` wraps any ``PriceLoader``. Given the records up front, it
fetches each distinct symbol once over the union of the windows those records
need, then serves every per-record request by slicing the cached series. Cost
drops to one call per distinct symbol plus one for the benchmark. It satisfies
the same call signature, so the evaluator needs no change.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import date, timedelta

import pandas as pd

from analyst_service.core.persistence import PersistedAnalysis
from backtesting.evaluator import PriceLoader


logger = logging.getLogger(__name__)

# The evaluator looks up to 3 months forward; fetch a margin beyond that.
FORWARD_WINDOW_DAYS = 120


class BatchPriceLoader:
    """A PriceLoader that fetches each symbol once and slices thereafter."""

    def __init__(
        self,
        loader: PriceLoader,
        records: Iterable[PersistedAnalysis],
        *,
        benchmark_symbol: str = "SPY",
        forward_window_days: int = FORWARD_WINDOW_DAYS,
    ) -> None:
        self._loader = loader
        self._benchmark_symbol = benchmark_symbol
        self._forward_window_days = forward_window_days
        self._cache: dict[str, pd.Series] = {}
        self._windows: dict[str, tuple[date, date]] = {}
        self._plan(list(records))

    def _plan(self, records: list[PersistedAnalysis]) -> None:
        """Work out the union window each symbol needs, before any fetching."""
        for record in records:
            start = record.generated_at.date()
            end = start + timedelta(days=self._forward_window_days)
            for symbol in (record.symbol, self._benchmark_symbol):
                key = symbol.upper()
                existing = self._windows.get(key)
                if existing is None:
                    self._windows[key] = (start, end)
                else:
                    self._windows[key] = (min(existing[0], start), max(existing[1], end))

    def __call__(self, symbol: str, start: date, end: date) -> pd.Series:
        key = symbol.upper()
        series = self._cache.get(key)
        if series is None:
            window = self._windows.get(key, (start, end))
            fetch_start = min(window[0], start)
            fetch_end = max(window[1], end)
            try:
                series = _as_series(self._loader(symbol, fetch_start, fetch_end))
            except Exception as exc:
                # One dead symbol must not take the whole report down. The
                # evaluator already treats an empty series as "price history
                # unavailable" and records a skipped_reason.
                logger.warning("price fetch failed for %s: %s", symbol, exc)
                series = pd.Series(dtype=float)
            self._cache[key] = series

        if series.empty:
            return series
        mask = (series.index >= pd.Timestamp(start)) & (series.index <= pd.Timestamp(end))
        return series[mask]


def _as_series(values: pd.Series | pd.DataFrame) -> pd.Series:
    if isinstance(values, pd.DataFrame):
        column = "Close" if "Close" in values else "close" if "close" in values else None
        values = values[column] if column else pd.Series(dtype=float)
    series = pd.to_numeric(values, errors="coerce").dropna().astype(float)
    if series.empty:
        return series
    index = pd.DatetimeIndex(series.index)
    if index.tz is not None:
        index = index.tz_localize(None)
    series.index = index.normalize()
    return series[~series.index.duplicated(keep="last")].sort_index()
