from __future__ import annotations

from collections.abc import Callable
from datetime import date
import os
import tempfile
from pathlib import Path

import pandas as pd

from backtesting.free_price_dataset import fetch_free_adjusted_ohlcv, normalize_ohlcv

DEFAULT_FREE_PRICE_CACHE_DIR = Path(__file__).resolve().parent / "cache" / "free_price"
PriceFetcher = Callable[[str, date, date], pd.DataFrame]


def load_or_fetch_free_adjusted_ohlcv(
    symbol: str,
    start: date,
    end: date,
    *,
    cache_dir: Path = DEFAULT_FREE_PRICE_CACHE_DIR,
    refresh: bool = False,
    fetcher: PriceFetcher = fetch_free_adjusted_ohlcv,
) -> pd.DataFrame:
    """Return a requested period, extending a local raw-price cache only when needed."""

    if start > end:
        raise ValueError("start must not be after end")
    path = cache_path(cache_dir, symbol)
    cached = read_cached_ohlcv(path)
    if not refresh and _covers(cached, start, end):
        return _slice(cached, start, end)

    fetch_start = min(start, cached.index.min().date()) if not cached.empty else start
    fetch_end = max(end, cached.index.max().date()) if not cached.empty else end
    fetched = fetcher(symbol, fetch_start, fetch_end)
    frames = [history for history in (cached, fetched) if not history.empty]
    combined = normalize_ohlcv(pd.concat(frames)) if frames else cached
    if not combined.empty:
        write_cached_ohlcv(path, combined)
    return _slice(combined, start, end)


def cache_path(cache_dir: Path, symbol: str) -> Path:
    safe_symbol = "".join(character if character.isalnum() or character in {"-", "_"} else "_" for character in symbol.upper())
    return cache_dir / f"{safe_symbol}.csv"


def read_cached_ohlcv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    try:
        return normalize_ohlcv(pd.read_csv(path, index_col="date", parse_dates=True))
    except (OSError, ValueError, pd.errors.ParserError):
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])


def write_cached_ohlcv(path: Path, history: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False) as temporary_file:
        temporary_path = Path(temporary_file.name)
    try:
        normalize_ohlcv(history).to_csv(temporary_path, index_label="date")
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _covers(history: pd.DataFrame, start: date, end: date) -> bool:
    return not history.empty and history.index.min().date() <= start and history.index.max().date() >= end


def _slice(history: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
    if history.empty:
        return history
    return history.loc[pd.Timestamp(start) : pd.Timestamp(end)].copy()
