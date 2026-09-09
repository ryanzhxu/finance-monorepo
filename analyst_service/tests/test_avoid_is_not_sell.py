"""`avoid` must never become a sell instruction.

Vincent's AGENTS.md, on the execution semantics:

    "Avoid is not Sell and must not produce a fake exit plan."

His engine keeps them distinct too — executionIntent maps sell to "exit" and
avoid to "avoid". Collapsing avoid onto Direction.SELL tells someone already
holding the stock to get out, when the engine only meant "do not enter".
Direction has three members and his vocabulary has seven, so the raw action
travels alongside rather than being reconstructed from the projection.
"""

from __future__ import annotations

import pytest

from shared.enums import DecisionAction, Direction, Horizon
from shared.models import Signal

from analyst_service.core.aggregator import aggregate_recommendation
from analyst_service.core.technical_provider import ACTION_TO_DIRECTION, verdict_from_external


THRESHOLDS = {"vote": {"buy_above": 0.2, "sell_below": -0.2}}


def _payload(action: str, price_state: str | None = None) -> dict[str, object]:
    payload: dict[str, object] = {
        "producer": "vincent-stock-decision-dashboard",
        "action": action,
        "confidence": 70,
    }
    if price_state:
        payload["priceState"] = price_state
    return payload


def test_avoid_does_not_become_sell() -> None:
    assert ACTION_TO_DIRECTION[DecisionAction.AVOID] is not Direction.SELL


def test_avoid_projects_to_hold() -> None:
    verdict = verdict_from_external(_payload("avoid", "BREAKDOWN_ZONE"))

    assert verdict.direction is Direction.HOLD


def test_sell_still_projects_to_sell() -> None:
    verdict = verdict_from_external(_payload("sell", "BREAKDOWN_ZONE"))

    assert verdict.direction is Direction.SELL


def test_avoid_is_distinguishable_from_a_real_hold() -> None:
    # Both project to HOLD, so the raw action has to survive or the difference
    # between "do not enter" and "keep holding" is silently lost.
    avoid = verdict_from_external(_payload("avoid", "INVALID_LANDSCAPE"))
    hold = verdict_from_external(_payload("hold", "NEUTRAL_ZONE"))

    assert avoid.direction is hold.direction
    assert avoid.action is DecisionAction.AVOID
    assert hold.action is DecisionAction.HOLD


def test_execution_intent_is_carried_from_his_vocabulary() -> None:
    # His mapping: strong_buy/buy -> enter, accumulate -> add, hold -> hold,
    # trim -> reduce, sell -> exit, avoid -> avoid.
    for action, intent in [
        ("strong_buy", "enter"),
        ("buy", "enter"),
        ("accumulate", "add"),
        ("hold", "hold"),
        ("trim", "reduce"),
        ("sell", "exit"),
        ("avoid", "avoid"),
    ]:
        verdict = verdict_from_external(_payload(action))
        assert verdict.execution_intent == intent, action


def test_recommendation_exposes_the_raw_action_and_intent() -> None:
    verdict = verdict_from_external(_payload("avoid", "BREAKDOWN_ZONE"))
    signals = [Signal(dimension="EPS Surprise", signal=Direction.BUY, weight=2.0, note="beat")]

    recommendation = aggregate_recommendation(
        signals, Horizon.THREE_TO_SIX_MONTHS, THRESHOLDS, 100, None, {}, technical_verdict=verdict
    )

    assert recommendation.direction is Direction.HOLD
    assert recommendation.technical_action == DecisionAction.AVOID
    assert recommendation.technical_execution_intent == "avoid"


def test_avoid_never_produces_an_exit_review_action() -> None:
    # review_action drives what a consumer does. "avoid" must not land on the
    # trim/exit path.
    verdict = verdict_from_external(_payload("avoid", "BREAKDOWN_ZONE"))

    recommendation = aggregate_recommendation(
        [Signal(dimension="PE Percentile", signal=Direction.HOLD, weight=1.0, note="mid")],
        Horizon.THREE_TO_SIX_MONTHS,
        THRESHOLDS,
        100,
        None,
        {},
        technical_verdict=verdict,
    )

    assert recommendation.review_action != "trim_review"
