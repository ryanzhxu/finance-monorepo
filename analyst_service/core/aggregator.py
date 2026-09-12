from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from shared.data_quality import FreshValue
from shared.enums import Direction, Freshness, TechnicalSource
from shared.models import (
    EntryBlock,
    Fundamentals,
    Horizon,
    Macro,
    Recommendation,
    Sentiment,
    Signal,
    SupportingContext,
    TechnicalVerdict,
)

from analyst_service.core.data_fetcher import fetch_fundamentals, fetch_macro, fetch_sentiment
from analyst_service.core.technical_provider import (
    EXTERNAL_TECHNICAL_DIMENSION,
    substitute_technical_signals,
)


logger = logging.getLogger(__name__)


SCORES = {Direction.BUY: 1.0, Direction.HOLD: 0.0, Direction.SELL: -1.0}
CATEGORY_PREFIXES = {
    # "technical" matches the synthesized signal an external engine's verdict
    # becomes; the rest match the locally computed indicators.
    "technical": ("rsi", "macd", "ma", "bollinger", "volume", "support", "breakout", "technical"),
    "fundamental": ("eps", "pe", "analyst", "fcf", "revenue", "gross", "valuation"),
    "sentiment": ("put", "iv", "institutional", "short", "news"),
    "macro": ("macro", "fomc"),
}


def _missing_fresh_value(value: Any) -> FreshValue[Any]:
    return FreshValue(value=value, freshness=Freshness.MISSING, as_of=None)


def _empty_weighted_vote() -> dict[Direction, float]:
    return {Direction.BUY: 0.0, Direction.HOLD: 0.0, Direction.SELL: 0.0}


def _match_category(dimension: str) -> str | None:
    normalized = dimension.strip().lower()
    for category, prefixes in CATEGORY_PREFIXES.items():
        if any(normalized.startswith(prefix) for prefix in prefixes):
            return category
    return None


def _weighted_votes_by_category(
    signals: list[Signal],
) -> tuple[dict[str, dict[Direction, float]], dict[str, list[Signal]]]:
    votes = {category: _empty_weighted_vote() for category in CATEGORY_PREFIXES}
    grouped = {category: [] for category in CATEGORY_PREFIXES}
    for signal in signals:
        category = _match_category(signal.dimension)
        if category is None:
            continue
        votes[category][signal.signal] += float(signal.weight)
        grouped[category].append(signal)
    for category_votes in votes.values():
        for direction, value in list(category_votes.items()):
            category_votes[direction] = round(value, 4)
    return votes, grouped


def _dominant_direction(weighted_vote: dict[Direction, float]) -> Direction:
    return max((Direction.BUY, Direction.HOLD, Direction.SELL), key=lambda direction: weighted_vote.get(direction, 0.0))


def _conflict_summary(
    technical_direction: Direction,
    technical_supporters: int,
    technical_total: int,
    fundamental_direction: Direction,
    fundamental_supporters: int,
    fundamental_total: int,
) -> str:
    # English only, for the LLM narrative prompt (analyst_service/core/narrator.py).
    # The UI localizes this itself from the conflict_* fields on Recommendation.
    return (
        f"Technicals lean {technical_direction.value} ({technical_supporters}/{technical_total} signals) "
        f"but fundamentals lean {fundamental_direction.value} ({fundamental_supporters}/{fundamental_total} signals)."
    )


def _external_conflict_summary(direction: Direction, supporting_context: SupportingContext) -> str:
    return (
        f"Vincent's technical engine calls {direction.value}, but Ryan's fundamental, sentiment and macro "
        f"context leans {supporting_context.direction.value}."
    )


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


def _build_supporting_context(
    signals: list[Signal],
    thresholds: dict[str, Any],
    action: Direction,
) -> SupportingContext | None:
    """Summarize Ryan's non-technical layers without letting them move the action.

    Returns None when there is nothing to say. "No non-technical evidence" is
    not the same claim as "the non-technical evidence says HOLD".
    """
    non_technical = [signal for signal in signals if _match_category(signal.dimension) != "technical"]
    total_weight = sum(signal.weight for signal in non_technical)
    if not non_technical or total_weight <= 0:
        return None

    weighted_score = sum(SCORES[signal.signal] * signal.weight for signal in non_technical) / total_weight
    if weighted_score > thresholds["vote"]["buy_above"]:
        direction = Direction.BUY
    elif weighted_score < thresholds["vote"]["sell_below"]:
        direction = Direction.SELL
    else:
        direction = Direction.HOLD

    majority_weight = sum(signal.weight for signal in non_technical if signal.signal == direction)
    category_votes, _ = _weighted_votes_by_category(non_technical)
    return SupportingContext(
        direction=direction,
        confidence=round(majority_weight / total_weight, 4),
        agrees_with_action=direction == action,
        weighted_score=round(weighted_score, 4),
        fundamental_vote=category_votes["fundamental"],
        sentiment_vote=category_votes["sentiment"],
        macro_vote=category_votes["macro"],
        signals=non_technical,
    )


def aggregate_recommendation(
    signals: list[Signal],
    horizon: Horizon,
    thresholds: dict[str, Any],
    data_quality_score: int,
    entry: EntryBlock | None,
    freshness: dict[str, Freshness | str],
    macro: Macro | None = None,
    apply_overrides: bool = True,
    technical_verdict: TechnicalVerdict | None = None,
    displaced_local_verdict: TechnicalVerdict | None = None,
) -> Recommendation:
    # An external verdict replaces the local technical block rather than blending
    # with it: Ryan and Vincent agreed Vincent's engine owns the technical layer.
    # Callers that already substituted (so their response can report the signals
    # actually voted on) pass the displaced local verdict in instead.
    displaced_local = displaced_local_verdict
    external = technical_verdict is not None and technical_verdict.source is TechnicalSource.EXTERNAL
    if external:
        already_substituted = any(
            signal.dimension == EXTERNAL_TECHNICAL_DIMENSION for signal in signals
        )
        if not already_substituted:
            signals, displaced_local = substitute_technical_signals(signals, technical_verdict)

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
    category_votes, category_signals = _weighted_votes_by_category(signals)
    technical_direction = _dominant_direction(category_votes["technical"])
    fundamental_direction = _dominant_direction(category_votes["fundamental"])
    technical_signal_count = len(category_signals["technical"])
    fundamental_signal_count = len(category_signals["fundamental"])
    conflict_detected = (
        technical_signal_count >= 2
        and fundamental_signal_count >= 2
        and technical_direction != fundamental_direction
    )
    technical_supporters = sum(
        1 for signal in category_signals["technical"] if signal.signal == technical_direction
    )
    fundamental_supporters = sum(
        1 for signal in category_signals["fundamental"] if signal.signal == fundamental_direction
    )
    conflict_summary = (
        _conflict_summary(
            technical_direction,
            technical_supporters,
            technical_signal_count,
            fundamental_direction,
            fundamental_supporters,
            fundamental_signal_count,
        )
        if conflict_detected
        else None
    )
    # Captured before the external branch can overwrite conflict_detected, so
    # the blended conflict_* fields below only ever describe the blended path.
    blended_conflict_detected = conflict_detected
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
        if not external:
            direction = Direction.HOLD
        if "fomc_proximity_override" not in risk_flags:
            risk_flags.append("fomc_proximity_override")

    supporting_context: SupportingContext | None = None
    if external:
        # Vincent's engine forbids fundamental, valuation, options and news data
        # from entering a recommendation, and says there is no overall action.
        # So his verdict IS the action and his confidence IS the confidence.
        # Ryan's layers are computed and reported, but cannot move either.
        direction = technical_verdict.direction
        confidence = technical_verdict.confidence
        supporting_context = _build_supporting_context(signals, thresholds, direction)
        # The signal-count heuristic above needs >=2 signals per category, but
        # substitution collapses "technical" to his one verdict signal, so it
        # never fires here. Supporting context already carries the comparison
        # Ryan's layers vs. his action; reuse it so the narrative still gets
        # told to name the tension instead of going silent about it.
        if supporting_context is not None and not supporting_context.agrees_with_action:
            conflict_detected = True
            conflict_summary = _external_conflict_summary(direction, supporting_context)
        else:
            conflict_detected = False
            conflict_summary = None

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
        technical_vote=category_votes["technical"],
        fundamental_vote=category_votes["fundamental"],
        sentiment_vote=category_votes["sentiment"],
        macro_vote=category_votes["macro"],
        conflict_detected=conflict_detected,
        conflict_summary=conflict_summary,
        conflict_technical_direction=technical_direction if blended_conflict_detected else None,
        conflict_technical_supporters=technical_supporters if blended_conflict_detected else None,
        conflict_technical_total=technical_signal_count if blended_conflict_detected else None,
        conflict_fundamental_direction=fundamental_direction if blended_conflict_detected else None,
        conflict_fundamental_supporters=fundamental_supporters if blended_conflict_detected else None,
        conflict_fundamental_total=fundamental_signal_count if blended_conflict_detected else None,
        weighted_score=round(weighted_score, 4),
        technical_target_high=max(entry.resistance_levels) if entry and entry.resistance_levels else None,
        technical_target_low=max(entry.support_levels) if entry and entry.support_levels else None,
        stop_loss_suggestion=entry.stop_loss_suggestion if entry else None,
        horizon=horizon,
        review_action=review_action,
        risk_flags=risk_flags,
        technical_source=(
            technical_verdict.source if technical_verdict is not None else TechnicalSource.LOCAL
        ),
        technical_producer=technical_verdict.producer if technical_verdict is not None else None,
        technical_price_state=technical_verdict.price_state if technical_verdict is not None else None,
        technical_action=technical_verdict.action if technical_verdict is not None else None,
        technical_execution_intent=(
            technical_verdict.execution_intent if technical_verdict is not None else None
        ),
        local_technical_direction=displaced_local.direction if displaced_local is not None else None,
        technical_agreement=(
            None
            if technical_verdict is None or displaced_local is None
            else technical_verdict.direction == displaced_local.direction
        ),
        supporting_context=supporting_context,
    )
