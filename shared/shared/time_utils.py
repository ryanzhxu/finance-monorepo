from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from shared.config_loader import load_yaml_config

US_EASTERN = ZoneInfo("America/New_York")
REGULAR_SESSION_OPEN = time(hour=9, minute=30)
REGULAR_SESSION_CLOSE = time(hour=16, minute=0)
HOLIDAY_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "us_equity_market_holidays.yaml"


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def age_in_days(as_of: datetime, now: datetime | None = None) -> float:
    now = ensure_utc(now or datetime.now(timezone.utc))
    return max(0.0, (now - ensure_utc(as_of)).total_seconds() / 86400)


def is_stale(as_of: datetime | None, ttl_seconds: int, now: datetime | None = None) -> bool:
    if as_of is None:
        return True
    now = ensure_utc(now or datetime.now(timezone.utc))
    return (now - ensure_utc(as_of)).total_seconds() > ttl_seconds


def in_new_york(value: datetime) -> datetime:
    return ensure_utc(value).astimezone(US_EASTERN)


@lru_cache(maxsize=1)
def us_equity_market_holidays() -> set[date]:
    config = load_yaml_config(HOLIDAY_CONFIG_PATH, required_keys={"holidays"})
    holidays: set[date] = set()
    for entry in config["holidays"]:
        if isinstance(entry, date):
            holidays.add(entry)
        else:
            holidays.add(date.fromisoformat(str(entry)))
    return holidays


def is_us_equity_trading_day(value: date | datetime) -> bool:
    trading_date = value.date() if isinstance(value, datetime) else value
    return trading_date.weekday() < 5 and trading_date not in us_equity_market_holidays()


def is_us_equity_market_open(value: datetime) -> bool:
    local = in_new_york(value)
    return (
        is_us_equity_trading_day(local)
        and REGULAR_SESSION_OPEN <= local.time() < REGULAR_SESSION_CLOSE
    )


def previous_us_equity_trading_day(value: date | datetime) -> date:
    cursor = value.date() if isinstance(value, datetime) else value
    cursor -= timedelta(days=1)
    while not is_us_equity_trading_day(cursor):
        cursor -= timedelta(days=1)
    return cursor


def latest_completed_us_equity_trading_day(value: datetime) -> date:
    local = in_new_york(value)
    if is_us_equity_trading_day(local):
        if local.time() >= REGULAR_SESSION_CLOSE:
            return local.date()
        return previous_us_equity_trading_day(local.date())
    return previous_us_equity_trading_day(local.date())
