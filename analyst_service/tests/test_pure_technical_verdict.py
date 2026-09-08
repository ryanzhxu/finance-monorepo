"""Vincent's technical verdict stays his; Ryan's layers sit beside it.

His AGENTS.md is explicit: fundamental, valuation, options and news data must
never enter a recommendation, and there is no overall action. So when his engine
speaks, its action is the action — Ryan's fundamentals, sentiment and macro are
reported as separate supporting context that cannot move it.
"""

from __future__ import annotations

import pytest

from shared.enums import Direction, Horizon, TechnicalSource
from shared.models import Signal

from analyst_service.core.aggregator import aggregate_recommendation
from analyst_service.core.technical_provider import verdict_from_external


THRESHOLDS = {"vote": {"buy_above": 0.2, "sell_below": -0.2}}


def _external(**overrides: object):
    payload: dict[str, object] = {
        "producer": "vincent-stock-decision-dashboard",
        "action": "buy",
        "confidence": 80,
        "priceState": "IN_OPPORTUNITY_ZONE",
    }
    payload.update(overrides)
    return verdict_from_external(payload)


def _bullish_technicals() -> list[Signal]:
    return [
        Signal(dimension="RSI 14", signal=Direction.BUY, weight=1.0, note="oversold"),
        Signal(dimension="MACD", signal=Direction.BUY, weight=1.0, note="histogram positive"),
    ]


def _bearish_fundamentals() -> list[Signal]:
    # Heavy enough that a blend would drag the final call to SELL.
    return [
        Signal(dimension="EPS Surprise", signal=Direction.SELL, weight=2.0, note="miss"),
        Signal(dimension="PE Percentile", signal=Direction.SELL, weight=1.0, note="rich"),
        Signal(dimension="News Sentiment", signal=Direction.SELL, weight=0.5, note="negative"),
        Signal(dimension="FOMC Proximity", signal=Direction.SELL, weight=1.0, note="event risk"),
    ]


# --- the action is Vincent's, not a blend -----------------------------------


def test_his_action_survives_hostile_fundamentals() -> None:
    verdict = _external(action="buy")
    signals = _bullish_technicals() + _bearish_fundamentals()

    recommendation = aggregate_recommendation(
        signals, Horizon.THREE_TO_SIX_MONTHS, THRESHOLDS, 100, None, {}, technical_verdict=verdict
    )

    assert recommendation.direction is Direction.BUY
    assert recommendation.technical_source is TechnicalSource.EXTERNAL


def test_his_sell_survives_friendly_fundamentals() -> None:
    verdict = _external(action="sell", priceState="BREAKDOWN_ZONE")
    signals = _bullish_technicals() + [
        Signal(dimension="EPS Surprise", signal=Direction.BUY, weight=2.0, note="beat"),
        Signal(dimension="Analyst Ratings", signal=Direction.BUY, weight=1.5, note="upgrades"),
    ]

    recommendation = aggregate_recommendation(
        signals, Horizon.THREE_TO_SIX_MONTHS, THRESHOLDS, 100, None, {}, technical_verdict=verdict
    )

    assert recommendation.direction is Direction.SELL


def test_confidence_is_his_not_recomputed_from_the_blend() -> None:
    verdict = _external(confidence=80)

    recommendation = aggregate_recommendation(
        _bearish_fundamentals(),
        Horizon.THREE_TO_SIX_MONTHS,
        THRESHOLDS,
        100,
        None,
        {},
        technical_verdict=verdict,
    )

    assert recommendation.confidence == pytest.approx(0.8)


# --- Ryan's layers are reported, and cannot move the action -----------------


def test_supporting_context_reports_the_non_technical_direction() -> None:
    verdict = _external(action="buy")
    signals = _bullish_technicals() + _bearish_fundamentals()

    recommendation = aggregate_recommendation(
        signals, Horizon.THREE_TO_SIX_MONTHS, THRESHOLDS, 100, None, {}, technical_verdict=verdict
    )

    assert recommendation.supporting_context is not None
    assert recommendation.supporting_context.direction is Direction.SELL
    # It disagrees with his call, and says so, without changing it.
    assert recommendation.supporting_context.agrees_with_action is False
    assert recommendation.direction is Direction.BUY


def test_supporting_context_excludes_technical_signals() -> None:
    verdict = _external()
    signals = _bullish_technicals() + _bearish_fundamentals()

    recommendation = aggregate_recommendation(
        signals, Horizon.THREE_TO_SIX_MONTHS, THRESHOLDS, 100, None, {}, technical_verdict=verdict
    )

    dimensions = {signal.dimension for signal in recommendation.supporting_context.signals}
    assert "RSI 14" not in dimensions
    assert "MACD" not in dimensions
    assert "EPS Surprise" in dimensions


def test_supporting_context_is_none_without_an_external_verdict() -> None:
    # With no external verdict there is no pure action to protect, so the
    # existing blended behavior stands unchanged.
    recommendation = aggregate_recommendation(
        _bullish_technicals() + _bearish_fundamentals(),
        Horizon.THREE_TO_SIX_MONTHS,
        THRESHOLDS,
        100,
        None,
        {},
    )

    assert recommendation.supporting_context is None
    assert recommendation.technical_source is TechnicalSource.LOCAL


def test_supporting_context_handles_no_non_technical_signals() -> None:
    verdict = _external()

    recommendation = aggregate_recommendation(
        _bullish_technicals(), Horizon.THREE_TO_SIX_MONTHS, THRESHOLDS, 100, None, {}, technical_verdict=verdict
    )

    # Nothing to say is not the same as saying HOLD.
    assert recommendation.supporting_context is None


# --- his constraints hold ---------------------------------------------------


def test_no_averaging_across_the_two_engines() -> None:
    # His BUY and a bearish context must not average into HOLD.
    verdict = _external(action="buy")

    recommendation = aggregate_recommendation(
        _bearish_fundamentals(),
        Horizon.THREE_TO_SIX_MONTHS,
        THRESHOLDS,
        100,
        None,
        {},
        technical_verdict=verdict,
    )

    assert recommendation.direction is Direction.BUY
    assert recommendation.supporting_context.direction is Direction.SELL


def test_conflict_detected_when_supporting_context_disagrees_with_his_action() -> None:
    # The old technical-vs-fundamental heuristic needs >=2 signals per side, but
    # substitution collapses the technical category to his one verdict signal,
    # so it never fires once an external verdict is present. The narrative
    # prompt only names a tension when conflict_detected is True, so a silent
    # False here would hide the exact disagreement supporting_context exists to
    # surface: his BUY against fundamentals that lean the opposite way.
    verdict = _external(action="buy")
    signals = _bullish_technicals() + _bearish_fundamentals()

    recommendation = aggregate_recommendation(
        signals, Horizon.THREE_TO_SIX_MONTHS, THRESHOLDS, 100, None, {}, technical_verdict=verdict
    )

    assert recommendation.conflict_detected is True
    assert recommendation.conflict_summary is not None
    assert "buy" in recommendation.conflict_summary.lower()
    assert "sell" in recommendation.conflict_summary.lower()


def test_conflict_not_detected_when_supporting_context_agrees_with_his_action() -> None:
    verdict = _external(action="buy")
    signals = _bullish_technicals() + [
        Signal(dimension="EPS Surprise", signal=Direction.BUY, weight=2.0, note="beat"),
    ]

    recommendation = aggregate_recommendation(
        signals, Horizon.THREE_TO_SIX_MONTHS, THRESHOLDS, 100, None, {}, technical_verdict=verdict
    )

    assert recommendation.supporting_context.agrees_with_action is True
    assert recommendation.conflict_detected is False
    assert recommendation.conflict_summary is None


def test_fomc_override_cannot_overrule_his_action() -> None:
    # The FOMC hold is Ryan's event-risk policy. It is context, not his call,
    # so it must surface as a risk flag rather than rewrite the action.
    from shared.models import Macro

    verdict = _external(action="buy")
    macro = Macro(days_to_next_fomc=1)
    thresholds = {**THRESHOLDS, "signals": {"fomc_force_hold_days": 3}}

    recommendation = aggregate_recommendation(
        _bearish_fundamentals(),
        Horizon.THREE_TO_SIX_MONTHS,
        thresholds,
        100,
        None,
        {},
        macro=macro,
        apply_overrides=True,
        technical_verdict=verdict,
    )

    assert recommendation.direction is Direction.BUY
    assert "fomc_proximity_override" in recommendation.risk_flags
