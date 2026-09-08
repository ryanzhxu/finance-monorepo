"""The seam where an external technical engine replaces the local one.

Ryan and Vincent agreed on 2026-08-28 that Vincent's technical analysis system
supplies the technical layer while every other layer stays here. This module is
that boundary: it turns a decision.v1 payload into the same `TechnicalVerdict`
the local technicals produce, so the aggregator never learns whose opinion it
is holding.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from shared.enums import DecisionAction, Direction, Horizon, PriceState, TechnicalSource
from shared.models import ExternalTechnicalVerdict, HorizonTechnicalVerdict, Signal, TechnicalVerdict


logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "technical_provider.yaml"

# decision.v1 has seven actions; Direction has three. accumulate and trim have no
# local source at all, which is precisely why they arrive from Vincent's side.
ACTION_TO_DIRECTION: dict[DecisionAction, Direction] = {
    DecisionAction.STRONG_BUY: Direction.BUY,
    DecisionAction.BUY: Direction.BUY,
    DecisionAction.ACCUMULATE: Direction.BUY,
    DecisionAction.HOLD: Direction.HOLD,
    DecisionAction.TRIM: Direction.SELL,
    DecisionAction.SELL: Direction.SELL,
    DecisionAction.AVOID: Direction.SELL,
}

# The legality table from the decision.v1 contract. An action outside its price
# state's row is a producer bug, and is refused rather than quietly accepted.
LEGAL_ACTIONS: dict[PriceState, frozenset[DecisionAction]] = {
    PriceState.IN_OPPORTUNITY_ZONE: frozenset(
        {DecisionAction.STRONG_BUY, DecisionAction.BUY, DecisionAction.ACCUMULATE}
    ),
    PriceState.NEAR_OPPORTUNITY_ZONE: frozenset({DecisionAction.HOLD}),
    PriceState.NEUTRAL_ZONE: frozenset({DecisionAction.HOLD}),
    PriceState.NEAR_REDUCE_ZONE: frozenset({DecisionAction.HOLD}),
    PriceState.IN_REDUCE_ZONE: frozenset({DecisionAction.TRIM, DecisionAction.SELL}),
    PriceState.BEYOND_REDUCE_ZONE: frozenset({DecisionAction.TRIM, DecisionAction.SELL}),
    PriceState.BREAKDOWN_ZONE: frozenset({DecisionAction.SELL, DecisionAction.AVOID}),
    PriceState.INVALID_LANDSCAPE: frozenset({DecisionAction.HOLD, DecisionAction.AVOID}),
}

# Dimension prefixes that aggregator.CATEGORY_PREFIXES maps to "technical".
LOCAL_TECHNICAL_PREFIXES = ("rsi", "macd", "ma", "bollinger", "volume", "support", "breakout")

EXTERNAL_TECHNICAL_DIMENSION = "Technical (external)"

# Sum of the technical entries in signal_weights.yaml. Those values are final
# pending a Phase 4 backtest, so they are read for the total rather than edited.
DEFAULT_EXTERNAL_TECHNICAL_WEIGHT = 7.6

# Vincent's engine emits independent short/mid/long verdicts. These three
# Horizon values are what "short/mid/long" mean here; 1D is Ryan's day-trade
# horizon and has no decision.v1 counterpart, so it is excluded.
SHORT_MID_LONG_HORIZONS: tuple[Horizon, ...] = (
    Horizon.ONE_WEEK,
    Horizon.TWO_TO_FOUR_WEEKS,
    Horizon.THREE_TO_SIX_MONTHS,
)

_SCORES = {Direction.BUY: 1.0, Direction.HOLD: 0.0, Direction.SELL: -1.0}


class TechnicalVerdictError(ValueError):
    """An external technical payload that cannot be trusted as-is."""


def _load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        return {}
    try:
        loaded = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        logger.warning("Could not read %s: %s", CONFIG_PATH.name, exc)
        return {}
    return loaded if isinstance(loaded, dict) else {}


def external_technical_weight() -> float:
    """The weight a substituted technical verdict carries in the blended vote.

    It equals the local technical block's total so that swapping the producer
    does not also change the technical-to-fundamental balance.
    """
    value = _load_config().get("external_technical_weight", DEFAULT_EXTERNAL_TECHNICAL_WEIGHT)
    try:
        weight = float(value)
    except (TypeError, ValueError):
        logger.warning("external_technical_weight is not a number; using the default")
        return DEFAULT_EXTERNAL_TECHNICAL_WEIGHT
    if weight <= 0:
        logger.warning("external_technical_weight must be positive; using the default")
        return DEFAULT_EXTERNAL_TECHNICAL_WEIGHT
    return weight


def is_local_technical(signal: Signal) -> bool:
    normalized = signal.dimension.strip().lower()
    return any(normalized.startswith(prefix) for prefix in LOCAL_TECHNICAL_PREFIXES)


def verdict_from_external(payload: ExternalTechnicalVerdict | dict[str, Any]) -> TechnicalVerdict:
    """Normalize a decision.v1 payload, or refuse it.

    Refusing matters more than accepting here: a malformed payload that silently
    became a confident HOLD would be indistinguishable from a real opinion.
    """
    if isinstance(payload, ExternalTechnicalVerdict):
        parsed = payload
    else:
        try:
            parsed = ExternalTechnicalVerdict.model_validate(payload)
        except ValidationError as exc:
            raise TechnicalVerdictError(f"external technical verdict is not decision.v1: {exc}") from exc

    _reject_overlapping_zones(parsed)
    _reject_illegal_action(parsed)

    return TechnicalVerdict(
        direction=ACTION_TO_DIRECTION[parsed.action],
        # decision.v1 is 0-100 and Recommendation.confidence is 0.0-1.0. Skipping
        # this division yields 0.7 where 70 was meant, and looks plausible.
        confidence=round(parsed.confidence / 100.0, 6),
        source=TechnicalSource.EXTERNAL,
        producer=parsed.producer,
        price_state=parsed.price_state,
        opportunity_range=parsed.opportunity_range,
        reduce_range=parsed.reduce_range,
        invalidation=parsed.invalidation,
        reasons=list(parsed.reasons),
        data_quality=parsed.data_quality,
    )


def _reject_overlapping_zones(parsed: ExternalTechnicalVerdict) -> None:
    opportunity = parsed.opportunity_range
    reduce = parsed.reduce_range
    for label, band in (("opportunityRange", opportunity), ("reduceRange", reduce)):
        if band is not None and band.low >= band.high:
            raise TechnicalVerdictError(f"{label}.low must be below {label}.high")
    if opportunity is not None and reduce is not None and opportunity.high >= reduce.low:
        raise TechnicalVerdictError("opportunityRange.high must be below reduceRange.low")


def _reject_illegal_action(parsed: ExternalTechnicalVerdict) -> None:
    if parsed.price_state is None:
        return
    permitted = LEGAL_ACTIONS[parsed.price_state]
    if parsed.action not in permitted:
        allowed = ", ".join(sorted(action.value for action in permitted))
        raise TechnicalVerdictError(
            f"action {parsed.action.value} is not legal for {parsed.price_state.value}; allowed: {allowed}"
        )


def verdict_from_local(signals: list[Signal]) -> TechnicalVerdict | None:
    """Summarize the locally computed technical signals as one verdict.

    Returns None when no technical signal was produced, so "we have no technical
    opinion" stays distinct from "our technical opinion is HOLD".
    """
    technical = [signal for signal in signals if is_local_technical(signal)]
    if not technical:
        return None

    total_weight = sum(signal.weight for signal in technical)
    if total_weight <= 0:
        return None

    votes = {direction: 0.0 for direction in (Direction.BUY, Direction.HOLD, Direction.SELL)}
    for signal in technical:
        votes[signal.signal] += float(signal.weight)
    direction = max(votes, key=lambda candidate: votes[candidate])

    return TechnicalVerdict(
        direction=direction,
        confidence=round(votes[direction] / total_weight, 6),
        source=TechnicalSource.LOCAL,
        producer=None,
        reasons=[signal.note for signal in technical],
    )


def synthesize_technical_signal(verdict: TechnicalVerdict, weight: float | None = None) -> Signal:
    """Express a verdict as the single technical signal the aggregator votes on."""
    resolved = external_technical_weight() if weight is None else weight
    producer = verdict.producer or "external engine"
    if verdict.price_state is not None:
        note = f"{producer}: {verdict.direction.value} in {verdict.price_state.value}"
    else:
        note = f"{producer}: {verdict.direction.value}"
    return Signal(
        dimension=EXTERNAL_TECHNICAL_DIMENSION,
        signal=verdict.direction,
        weight=resolved,
        note=note,
    )


def resolve_technical_verdict(
    supplied: ExternalTechnicalVerdict | dict[str, Any] | None,
) -> tuple[TechnicalVerdict | None, list[str]]:
    """Normalize a supplied verdict, or degrade to local technicals visibly.

    A payload that violates the contract must not take the analysis down, and it
    must not quietly pass either. Rejection returns no verdict plus a risk flag,
    so the caller can tell "Vincent's engine was used" from "it was ignored".
    """
    if supplied is None:
        return None, []
    try:
        return verdict_from_external(supplied), []
    except TechnicalVerdictError as exc:
        logger.warning("Rejected external technical verdict, using local technicals: %s", exc)
        return None, ["external_technical_rejected"]


def resolve_technical_verdicts_by_horizon(
    payloads: dict[Horizon, ExternalTechnicalVerdict | dict[str, Any]],
) -> list[HorizonTechnicalVerdict]:
    """Normalize a batch of per-horizon payloads for side-by-side reporting.

    Each horizon stands alone: a payload that fails decision.v1 validation is
    dropped rather than defaulted, so a partial engine outage yields fewer
    horizons rather than a fabricated one. Nothing here ranks or blends them.
    """
    resolved: list[HorizonTechnicalVerdict] = []
    for horizon in SHORT_MID_LONG_HORIZONS:
        payload = payloads.get(horizon)
        if payload is None:
            continue
        try:
            resolved.append(HorizonTechnicalVerdict(horizon=horizon, verdict=verdict_from_external(payload)))
        except TechnicalVerdictError as exc:
            logger.warning("Rejected external technical verdict for %s, omitting: %s", horizon.value, exc)
    return resolved


def substitute_technical_signals(
    signals: list[Signal], verdict: TechnicalVerdict
) -> tuple[list[Signal], TechnicalVerdict | None]:
    """Swap the local technical signals for the external verdict.

    Returns the voting signal list and the local verdict that was displaced, so
    callers can report the comparison without counting it twice.
    """
    displaced = verdict_from_local(signals)
    retained = [signal for signal in signals if not is_local_technical(signal)]
    return [*retained, synthesize_technical_signal(verdict)], displaced
