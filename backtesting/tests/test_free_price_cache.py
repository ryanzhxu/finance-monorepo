from datetime import date

import pandas as pd

from backtesting.free_price_cache import load_or_fetch_free_adjusted_ohlcv


def _history(start: str, count: int) -> pd.DataFrame:
    index = pd.date_range(start, periods=count, freq="B")
    close = pd.Series(range(100, 100 + count), index=index, dtype=float)
    return pd.DataFrame({"Open": close, "High": close + 1, "Low": close - 1, "Close": close, "Volume": 100}, index=index)


def test_price_cache_reuses_covered_history_without_fetching(tmp_path) -> None:
    calls: list[tuple[date, date]] = []

    def fetcher(symbol: str, start: date, end: date) -> pd.DataFrame:
        calls.append((start, end))
        return _history("2020-01-01", 10)

    first = load_or_fetch_free_adjusted_ohlcv("TEST", date(2020, 1, 1), date(2020, 1, 10), cache_dir=tmp_path, fetcher=fetcher)
    second = load_or_fetch_free_adjusted_ohlcv("TEST", date(2020, 1, 2), date(2020, 1, 9), cache_dir=tmp_path, fetcher=fetcher)

    assert not first.empty
    assert not second.empty
    assert calls == [(date(2020, 1, 1), date(2020, 1, 10))]
