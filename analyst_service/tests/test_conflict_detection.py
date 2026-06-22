from __future__ import annotations

from shared.enums import Direction, Horizon
from shared.models import Signal

from analyst_service.core.aggregator import aggregate_recommendation


THRESHOLDS = {"vote": {"buy_above": 0.2, "sell_below": -0.2}, "signals": {"fomc_force_hold_days": 2}}


def test_conflict_detected_when_technicals_and_fundamentals_disagree() -> None:
    signals = [
        Signal(dimension="RSI(14)", signal=Direction.BUY, weight=1.0, note="buy"),
        Signal(dimension="MACD", signal=Direction.BUY, weight=1.0, note="buy"),
        Signal(dimension="MA 50/200", signal=Direction.BUY, weight=1.0, note="buy"),
        Signal(dimension="EPS Surprise", signal=Direction.SELL, weight=1.0, note="sell"),
        Signal(dimension="PE Percentile", signal=Direction.SELL, weight=1.0, note="sell"),
        Signal(dimension="Analyst Ratings", signal=Direction.SELL, weight=1.0, note="sell"),
    ]

    recommendation = aggregate_recommendation(signals, Horizon.TWO_TO_FOUR_WEEKS, THRESHOLDS, 90, None, {})

    assert recommendation.conflict_detected is True
    assert recommendation.conflict_summary == "Technicals lean BUY (3/3 signals) but fundamentals lean SELL (3/3 signals)."


def test_conflict_not_detected_when_technicals_and_fundamentals_align() -> None:
    signals = [
        Signal(dimension="RSI(14)", signal=Direction.BUY, weight=1.0, note="buy"),
        Signal(dimension="MACD", signal=Direction.BUY, weight=1.0, note="buy"),
        Signal(dimension="MA 50/200", signal=Direction.BUY, weight=1.0, note="buy"),
        Signal(dimension="EPS Surprise", signal=Direction.BUY, weight=1.0, note="buy"),
        Signal(dimension="PE Percentile", signal=Direction.BUY, weight=1.0, note="buy"),
        Signal(dimension="Analyst Ratings", signal=Direction.BUY, weight=1.0, note="buy"),
    ]

    recommendation = aggregate_recommendation(signals, Horizon.TWO_TO_FOUR_WEEKS, THRESHOLDS, 90, None, {})

    assert recommendation.conflict_detected is False
    assert recommendation.conflict_summary is None


def test_conflict_not_detected_with_only_one_technical_signal() -> None:
    signals = [
        Signal(dimension="RSI(14)", signal=Direction.BUY, weight=1.0, note="buy"),
        Signal(dimension="EPS Surprise", signal=Direction.SELL, weight=1.0, note="sell"),
        Signal(dimension="PE Percentile", signal=Direction.SELL, weight=1.0, note="sell"),
        Signal(dimension="Analyst Ratings", signal=Direction.SELL, weight=1.0, note="sell"),
    ]

    recommendation = aggregate_recommendation(signals, Horizon.TWO_TO_FOUR_WEEKS, THRESHOLDS, 90, None, {})

    assert recommendation.conflict_detected is False
    assert recommendation.conflict_summary is None
