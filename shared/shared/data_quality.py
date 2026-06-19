from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Generic, TypeVar

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


def _is_present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, (list, tuple, set, dict, str)):
        return len(value) > 0
    return True


def _score_group(total_points: float, values: list[Any]) -> float:
    if not values:
        return 0.0
    present = sum(1 for value in values if _is_present(value))
    return total_points * (present / len(values))


def compute_analysis_data_quality(
    technicals: Any,
    fundamentals: Any,
    sentiment: Any,
    macro: Any,
) -> int:
    technical_values = [
        getattr(technicals, "rsi_14", None),
        getattr(technicals, "rsi_weekly", None),
        getattr(getattr(technicals, "macd", None), "histogram", None),
        getattr(technicals, "ma_50", None),
        getattr(technicals, "ma_200", None),
        getattr(technicals, "atr_14", None),
        getattr(technicals, "bb_upper", None),
        getattr(technicals, "bb_lower", None),
        getattr(technicals, "volume_ratio_90d", None),
        getattr(technicals, "support_levels", None),
        getattr(technicals, "resistance_levels", None),
    ]
    fundamentals_values = [
        getattr(fundamentals, "eps_surprise_pct", None),
        getattr(fundamentals, "pe_ratio", None),
        getattr(fundamentals, "pb_ratio", None),
        getattr(fundamentals, "ps_ratio", None),
        getattr(fundamentals, "ev_ebitda", None),
        getattr(fundamentals, "pe_percentile_5y", None),
        getattr(fundamentals, "revenue_growth_yoy_pct", None),
        getattr(fundamentals, "fcf_trend", None),
        getattr(fundamentals, "gross_margin_pct", None),
        getattr(fundamentals, "analyst_upgrades_30d", None),
        getattr(fundamentals, "analyst_downgrades_30d", None),
    ]
    sentiment_values = [
        getattr(sentiment, "put_call_ratio", None),
        getattr(sentiment, "iv_rank_approx", None) if getattr(sentiment, "iv_rank_approx", None) is not None else getattr(sentiment, "iv_rank", None),
        getattr(sentiment, "short_interest_pct", None),
        getattr(sentiment, "institutional_net_shares_last_13f", None),
    ]
    macro_values = [
        getattr(macro, "days_to_next_fomc", None),
        getattr(macro, "rate_cut_probability_pct", None),
        getattr(macro, "treasury_10y", None),
        getattr(macro, "vix", None),
    ]

    score = (
        _score_group(25.0, technical_values)
        + _score_group(30.0, fundamentals_values)
        + _score_group(25.0, sentiment_values)
        + _score_group(20.0, macro_values)
    )
    return max(0, min(100, round(score)))
