from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from shared.data_quality import FreshValue
from shared.enums import Direction, Freshness
from shared.models import EntryBlock, Fundamentals, Horizon, Macro, Recommendation, Sentiment, Signal

from analyst_service.core.data_fetcher import fetch_fundamentals, fetch_macro, fetch_sentiment


logger = logging.getLogger(__name__)


SCORES = {Direction.BUY: 1.0, Direction.HOLD: 0.0, Direction.SELL: -1.0}


def _missing_fresh_value(value: Any) -> FreshValue[Any]:
    return FreshValue(value=value, freshness=Freshness.MISSING, as_of=None)


def fetch_analysis_context(
    symbol: str,
    price_history: pd.DataFrame | None,
) -> tuple[FreshValue[Fundamentals], FreshValue[Sentiment], FreshValue[Macro]]:
    try:
        fundamentals = fetch_fundamentals(symbol)
    except Exception as exc:
        logger.warning("fundamentals fetch failed for %s: %s", symbol, exc)
        fundamentals = _missing_fresh_value(Fundamentals())

    try:
        sentiment = fetch_sentiment(symbol, price_history=price_history)
    except Exception as exc:
        logger.warning("sentiment fetch failed for %s: %s", symbol, exc)
        sentiment = _missing_fresh_value(Sentiment())

    try:
        macro = fetch_macro()
    except Exception as exc:
        logger.warning("macro fetch failed: %s", exc)
        macro = _missing_fresh_value(Macro())

    return fundamentals, sentiment, macro


def aggregate_recommendation(
    signals: list[Signal],
    horizon: Horizon,
    thresholds: dict[str, Any],
    data_quality_score: int,
    entry: EntryBlock | None,
    freshness: dict[str, Freshness | str],
    macro: Macro | None = None,
    apply_overrides: bool = True,
) -> Recommendation:
    if not signals:
        weighted_score = 0.0
        vote_direction = Direction.HOLD
        majority_fraction = 0.0
    else:
        total_weight = sum(signal.weight for signal in signals)
        weighted_score = sum(SCORES[signal.signal] * signal.weight for signal in signals) / total_weight
        if weighted_score > thresholds["vote"]["buy_above"]:
            vote_direction = Direction.BUY
        elif weighted_score < thresholds["vote"]["sell_below"]:
            vote_direction = Direction.SELL
        else:
            vote_direction = Direction.HOLD
        majority_weight = sum(signal.weight for signal in signals if signal.signal == vote_direction)
        majority_fraction = majority_weight / total_weight

    vote = {
        Direction.BUY: sum(1 for signal in signals if signal.signal == Direction.BUY),
        Direction.HOLD: sum(1 for signal in signals if signal.signal == Direction.HOLD),
        Direction.SELL: sum(1 for signal in signals if signal.signal == Direction.SELL),
    }
    confidence = round(max(0.0, min(1.0, majority_fraction * (data_quality_score / 100))), 4)
    risk_flags: list[str] = []
    if data_quality_score < 50:
        risk_flags.append("low_data_quality")
    if any(value == Freshness.STALE.value for value in freshness.values()):
        risk_flags.append("stale_data")

    direction = vote_direction
    if (
        apply_overrides
        and macro is not None
        and macro.days_to_next_fomc is not None
        and macro.days_to_next_fomc <= thresholds["signals"]["fomc_force_hold_days"]
    ):
        # Keep the weighted score and confidence tied to the underlying vote, but emit HOLD
        # near an FOMC event because the override reflects event-risk policy rather than signal math.
        direction = Direction.HOLD
        if "fomc_proximity_override" not in risk_flags:
            risk_flags.append("fomc_proximity_override")

    if direction == Direction.BUY:
        review_action = "add_watch"
    elif direction == Direction.SELL:
        review_action = "trim_review"
    else:
        review_action = "hold_monitor"

    return Recommendation(
        direction=direction,
        confidence=confidence,
        signal_vote=vote,
        weighted_score=round(weighted_score, 4),
        technical_target_high=max(entry.resistance_levels) if entry and entry.resistance_levels else None,
        technical_target_low=max(entry.support_levels) if entry and entry.support_levels else None,
        stop_loss_suggestion=entry.stop_loss_suggestion if entry else None,
        horizon=horizon,
        review_action=review_action,
        risk_flags=risk_flags,
    )
