from __future__ import annotations

from typing import Any

from shared.enums import Direction, Freshness
from shared.models import EntryBlock, Horizon, Recommendation, Signal


SCORES = {Direction.BUY: 1.0, Direction.HOLD: 0.0, Direction.SELL: -1.0}


def aggregate_recommendation(
    signals: list[Signal],
    horizon: Horizon,
    thresholds: dict[str, Any],
    data_quality_score: int,
    entry: EntryBlock | None,
    freshness: dict[str, Freshness | str],
) -> Recommendation:
    if not signals:
        weighted_score = 0.0
        direction = Direction.HOLD
        majority_fraction = 0.0
    else:
        total_weight = sum(signal.weight for signal in signals)
        weighted_score = sum(SCORES[signal.signal] * signal.weight for signal in signals) / total_weight
        if weighted_score > thresholds["vote"]["buy_above"]:
            direction = Direction.BUY
        elif weighted_score < thresholds["vote"]["sell_below"]:
            direction = Direction.SELL
        else:
            direction = Direction.HOLD
        majority_weight = sum(signal.weight for signal in signals if signal.signal == direction)
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
