from __future__ import annotations

from datetime import datetime, timezone

from shared.data_quality import FreshValue, compute_data_quality, freshness_label
from shared.enums import Freshness
from shared.time_utils import is_us_equity_market_open, latest_completed_us_equity_trading_day


def _utc(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def test_market_is_open_during_regular_session() -> None:
    assert is_us_equity_market_open(_utc(2026, 6, 15, 18, 0)) is True


def test_market_is_closed_on_weekend() -> None:
    assert is_us_equity_market_open(_utc(2026, 6, 13, 18, 0)) is False
    assert latest_completed_us_equity_trading_day(_utc(2026, 6, 13, 18, 0)).isoformat() == "2026-06-12"


def test_market_is_closed_on_holiday() -> None:
    assert is_us_equity_market_open(_utc(2026, 7, 3, 18, 0)) is False
    assert latest_completed_us_equity_trading_day(_utc(2026, 7, 3, 18, 0)).isoformat() == "2026-07-02"


def test_market_is_closed_after_hours() -> None:
    assert is_us_equity_market_open(_utc(2026, 6, 15, 21, 30)) is False
    assert latest_completed_us_equity_trading_day(_utc(2026, 6, 15, 21, 30)).isoformat() == "2026-06-15"


def test_last_close_label_and_quality_are_honest() -> None:
    item = FreshValue(value=123.0, freshness=Freshness.LAST_CLOSE, as_of=_utc(2026, 6, 12, 20, 0))
    assert freshness_label(item) == "last_close (2026-06-12)"
    assert compute_data_quality({"price": freshness_label(item)}) == 100
