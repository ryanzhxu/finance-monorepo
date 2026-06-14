from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Generic, TypeVar

from shared.enums import Freshness

T = TypeVar("T")


@dataclass(frozen=True)
class FreshValue(Generic[T]):
    value: T | None
    freshness: Freshness
    as_of: datetime | None


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def freshness_label(item: FreshValue[object]) -> str:
    if item.freshness == Freshness.LAST_CLOSE and item.as_of:
        return f"{item.freshness.value} ({item.as_of.date().isoformat()})"
    if item.freshness == Freshness.QUARTERLY and item.as_of:
        return item.as_of.date().isoformat()
    return item.freshness.value


def compute_data_quality(
    freshness_by_group: dict[str, Freshness | str],
    group_penalties: dict[str, int] | None = None,
    default_penalty: int = 15,
) -> int:
    score = 100.0
    for group, freshness in freshness_by_group.items():
        penalty = (group_penalties or {}).get(group, default_penalty)
        normalized = freshness.value if isinstance(freshness, Freshness) else str(freshness)
        if normalized == Freshness.MISSING.value:
            score -= penalty
        elif normalized == Freshness.STALE.value:
            score -= penalty * 0.5
        elif normalized == Freshness.ESTIMATED.value:
            score -= penalty * 0.25
    return max(0, min(100, round(score)))
