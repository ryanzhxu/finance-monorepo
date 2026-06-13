from __future__ import annotations

from datetime import datetime, timezone


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
