from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from analyst_service.core.data_fetcher import classify_price_freshness
from shared.enums import Freshness


def _frame(date_text: str) -> pd.DataFrame:
    index = pd.DatetimeIndex([pd.Timestamp(date_text)])
    return pd.DataFrame(
        {
            "open": [100.0],
            "high": [101.0],
            "low": [99.0],
            "close": [100.5],
            "volume": [1_000_000.0],
        },
        index=index,
    )


def _utc(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def test_price_is_delayed_during_market_hours() -> None:
    freshness, as_of = classify_price_freshness(_frame("2026-06-15"), now=_utc(2026, 6, 15, 18, 0))
    assert freshness == Freshness.DELAYED
    assert as_of == _utc(2026, 6, 15, 18, 0)


def test_price_is_last_close_on_weekend() -> None:
    freshness, as_of = classify_price_freshness(_frame("2026-06-12"), now=_utc(2026, 6, 13, 18, 0))
    assert freshness == Freshness.LAST_CLOSE
    assert as_of is not None
    assert as_of.date().isoformat() == "2026-06-12"


def test_price_is_last_close_on_market_holiday() -> None:
    freshness, as_of = classify_price_freshness(_frame("2026-07-02"), now=_utc(2026, 7, 3, 18, 0))
    assert freshness == Freshness.LAST_CLOSE
    assert as_of is not None
    assert as_of.date().isoformat() == "2026-07-02"


def test_price_is_last_close_after_hours() -> None:
    freshness, as_of = classify_price_freshness(_frame("2026-06-15"), now=_utc(2026, 6, 15, 21, 30))
    assert freshness == Freshness.LAST_CLOSE
    assert as_of is not None
    assert as_of.date().isoformat() == "2026-06-15"
