from __future__ import annotations

from shared.enums import Direction, Horizon
from shared.models import Signal

from analyst_service.core.aggregator import aggregate_recommendation


def test_weighted_vote_buy_when_score_above_threshold() -> None:
    signals = [
        Signal(dimension="A", signal=Direction.BUY, weight=2.0, note="buy"),
        Signal(dimension="B", signal=Direction.HOLD, weight=1.0, note="hold"),
        Signal(dimension="C", signal=Direction.SELL, weight=0.5, note="sell"),
    ]
    thresholds = {"vote": {"buy_above": 0.2, "sell_below": -0.2}}

    recommendation = aggregate_recommendation(signals, Horizon.TWO_TO_FOUR_WEEKS, thresholds, 80, None, {})

    assert recommendation.direction == Direction.BUY
    assert recommendation.weighted_score == 0.4286
    assert recommendation.confidence == 0.4571


def test_weighted_vote_hold_inside_threshold_band() -> None:
    signals = [
        Signal(dimension="A", signal=Direction.BUY, weight=1.0, note="buy"),
        Signal(dimension="B", signal=Direction.SELL, weight=1.0, note="sell"),
    ]
    thresholds = {"vote": {"buy_above": 0.2, "sell_below": -0.2}}

    recommendation = aggregate_recommendation(signals, Horizon.ONE_WEEK, thresholds, 100, None, {})

    assert recommendation.direction == Direction.HOLD
    assert recommendation.weighted_score == 0
