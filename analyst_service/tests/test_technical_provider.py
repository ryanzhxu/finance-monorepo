from __future__ import annotations

import pytest

from shared.enums import Direction, DecisionAction, Horizon, PriceState, TechnicalSource
from shared.models import Signal

from analyst_service.core.aggregator import aggregate_recommendation
from analyst_service.core.technical_provider import (
    TechnicalVerdictError,
    external_technical_weight,
    resolve_technical_verdicts_by_horizon,
    substitute_technical_signals,
    synthesize_technical_signal,
    verdict_from_external,
    verdict_from_local,
)


THRESHOLDS = {"vote": {"buy_above": 0.2, "sell_below": -0.2}}


def _external_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "contractVersion": "decision.v1",
        "producer": "vincent-stock-decision-dashboard",
        "action": "buy",
        "confidence": 70,
        "priceState": "IN_OPPORTUNITY_ZONE",
        "opportunityRange": {"low": 100.0, "high": 110.0},
        "reduceRange": {"low": 140.0, "high": 150.0},
        "invalidation": 95.0,
        "reasons": ["Weekly trend intact", "Pullback into demand"],
        "dataQuality": 88,
    }
    payload.update(overrides)
    return payload


def _landscape_free_payload(**overrides: object) -> dict[str, object]:
    """A payload with no priceState, so the legality table does not apply."""
    payload = _external_payload(**overrides)
    for key in ("priceState", "opportunityRange", "reduceRange"):
        payload.pop(key, None)
    return payload


def _local_technical_signals() -> list[Signal]:
    return [
        Signal(dimension="RSI 14", signal=Direction.BUY, weight=1.0, note="oversold"),
        Signal(dimension="MACD", signal=Direction.BUY, weight=1.0, note="histogram positive"),
        Signal(dimension="MA 50/200", signal=Direction.BUY, weight=1.5, note="golden cross"),
    ]


def _non_technical_signals() -> list[Signal]:
    return [
        Signal(dimension="EPS Surprise", signal=Direction.BUY, weight=2.0, note="beat"),
        Signal(dimension="PE Percentile", signal=Direction.HOLD, weight=1.0, note="mid range"),
        Signal(dimension="News Sentiment", signal=Direction.HOLD, weight=0.5, note="neutral"),
    ]


# --- action vocabulary ------------------------------------------------------


@pytest.mark.parametrize(
    ("action", "expected"),
    [
        ("strong_buy", Direction.BUY),
        ("buy", Direction.BUY),
        ("accumulate", Direction.BUY),
        ("hold", Direction.HOLD),
        ("trim", Direction.SELL),
        ("sell", Direction.SELL),
        # NOT SELL. His AGENTS.md: "Avoid is not Sell and must not produce a
        # fake exit plan." See test_avoid_is_not_sell.py.
        ("avoid", Direction.HOLD),
    ],
)
def test_every_decision_action_maps_to_a_direction(action: str, expected: Direction) -> None:
    verdict = verdict_from_external(_landscape_free_payload(action=action))

    assert verdict.direction is expected


def test_all_seven_actions_are_covered() -> None:
    # A new action member must not silently fall through to HOLD.
    for action in DecisionAction:
        verdict = verdict_from_external(_landscape_free_payload(action=action.value))
        assert verdict.direction in (Direction.BUY, Direction.HOLD, Direction.SELL)


def test_unknown_action_is_rejected_not_defaulted() -> None:
    with pytest.raises(TechnicalVerdictError):
        verdict_from_external(_external_payload(action="moon"))


def test_missing_action_is_rejected_not_treated_as_hold() -> None:
    payload = _external_payload()
    del payload["action"]

    with pytest.raises(TechnicalVerdictError):
        verdict_from_external(payload)


# --- confidence rescale -----------------------------------------------------


@pytest.mark.parametrize(
    ("external", "expected"),
    [(0, 0.0), (70, 0.7), (100, 1.0), (55.5, 0.555)],
)
def test_confidence_rescales_from_hundred_to_unit(external: float, expected: float) -> None:
    verdict = verdict_from_external(_external_payload(confidence=external))

    assert verdict.confidence == pytest.approx(expected)


def test_confidence_seventy_does_not_stay_seventy() -> None:
    # The exact trap logged as open question 16 on consolidation/decision-v1.
    verdict = verdict_from_external(_external_payload(confidence=70))

    assert verdict.confidence <= 1.0
    assert verdict.confidence != 70


def test_confidence_outside_the_contract_range_is_rejected() -> None:
    with pytest.raises(TechnicalVerdictError):
        verdict_from_external(_external_payload(confidence=101))


def test_data_quality_outside_the_contract_range_is_rejected() -> None:
    with pytest.raises(TechnicalVerdictError):
        verdict_from_external(_external_payload(dataQuality=101))
    with pytest.raises(TechnicalVerdictError):
        verdict_from_external(_external_payload(dataQuality=-1))


def test_data_quality_must_be_a_whole_number() -> None:
    # data_quality is `int` in the contract, unlike confidence which is `float`.
    with pytest.raises(TechnicalVerdictError):
        verdict_from_external(_external_payload(dataQuality=88.5))


def test_missing_producer_is_rejected() -> None:
    payload = _external_payload()
    del payload["producer"]

    with pytest.raises(TechnicalVerdictError):
        verdict_from_external(payload)


def test_empty_producer_is_accepted_matching_the_unconstrained_contract_field() -> None:
    # `producer: str` has no length constraint, so an empty string is a valid
    # (if useless) value. The Worker mirror must accept it too, or the same
    # payload would be treated as malformed by one engine and not the other.
    verdict = verdict_from_external(_landscape_free_payload(producer=""))

    assert verdict.producer == ""


def test_empty_producer_falls_back_to_a_default_label_when_synthesized() -> None:
    verdict = verdict_from_external(_landscape_free_payload(producer=""))
    signal = synthesize_technical_signal(verdict)

    assert signal.note == "external engine: BUY"


# --- structural fields ------------------------------------------------------


def test_external_verdict_carries_vincent_price_landscape() -> None:
    verdict = verdict_from_external(_external_payload())

    assert verdict.source is TechnicalSource.EXTERNAL
    assert verdict.producer == "vincent-stock-decision-dashboard"
    assert verdict.price_state is PriceState.IN_OPPORTUNITY_ZONE
    assert verdict.opportunity_range is not None
    assert verdict.opportunity_range.high == 110.0
    assert verdict.reduce_range is not None
    assert verdict.reduce_range.low == 140.0
    assert verdict.invalidation == 95.0
    assert verdict.reasons == ["Weekly trend intact", "Pullback into demand"]


def test_missing_optional_landscape_stays_none_rather_than_zero() -> None:
    payload = _external_payload()
    for key in ("priceState", "opportunityRange", "reduceRange", "invalidation", "dataQuality"):
        del payload[key]

    verdict = verdict_from_external(payload)

    assert verdict.price_state is None
    assert verdict.opportunity_range is None
    assert verdict.reduce_range is None
    assert verdict.invalidation is None
    assert verdict.data_quality is None


def test_explicit_null_invalidation_stays_none_rather_than_becoming_zero() -> None:
    verdict = verdict_from_external(_landscape_free_payload(invalidation=None))

    assert verdict.invalidation is None


def test_non_numeric_invalidation_is_rejected_not_silently_dropped() -> None:
    with pytest.raises(TechnicalVerdictError):
        verdict_from_external(_landscape_free_payload(invalidation="not-a-number"))


def test_reasons_that_is_not_a_list_is_rejected_not_silently_emptied() -> None:
    with pytest.raises(TechnicalVerdictError):
        verdict_from_external(_landscape_free_payload(reasons="not a list"))


def test_explicit_null_reasons_is_rejected_matching_the_non_optional_contract_field() -> None:
    with pytest.raises(TechnicalVerdictError):
        verdict_from_external(_landscape_free_payload(reasons=None))


def test_reasons_entry_that_is_not_a_string_is_rejected_not_silently_filtered_out() -> None:
    with pytest.raises(TechnicalVerdictError):
        verdict_from_external(_landscape_free_payload(reasons=["fine", 123]))


def test_overlapping_zones_are_rejected() -> None:
    payload = _external_payload(
        opportunityRange={"low": 100.0, "high": 150.0},
        reduceRange={"low": 140.0, "high": 160.0},
    )

    with pytest.raises(TechnicalVerdictError):
        verdict_from_external(payload)


def test_action_illegal_for_its_price_state_is_rejected() -> None:
    # decision.v1 legality table: IN_REDUCE_ZONE permits only trim or sell.
    payload = _external_payload(action="buy", priceState="IN_REDUCE_ZONE")

    with pytest.raises(TechnicalVerdictError):
        verdict_from_external(payload)


def test_legal_action_for_reduce_zone_is_accepted() -> None:
    verdict = verdict_from_external(_external_payload(action="trim", priceState="IN_REDUCE_ZONE"))

    assert verdict.direction is Direction.SELL


# --- local provider ---------------------------------------------------------


def test_local_verdict_summarizes_the_local_technical_signals() -> None:
    verdict = verdict_from_local(_local_technical_signals())

    assert verdict is not None
    assert verdict.source is TechnicalSource.LOCAL
    assert verdict.direction is Direction.BUY


def test_local_verdict_is_none_when_no_technical_signals_exist() -> None:
    assert verdict_from_local(_non_technical_signals()) is None


# --- weighting --------------------------------------------------------------


def test_external_technical_weight_matches_the_local_technical_block() -> None:
    # RSI_14 1.0 + MACD 1.0 + Bollinger_Bands 0.8 + Volume 1.0
    # + MA_50_200 1.5 + RSI_Weekly 1.5 + Support_Resistance 0.8
    assert external_technical_weight() == pytest.approx(7.6)


def test_synthesized_signal_is_categorized_as_technical() -> None:
    verdict = verdict_from_external(_external_payload())
    signal = synthesize_technical_signal(verdict)

    recommendation = aggregate_recommendation(
        [signal], Horizon.THREE_TO_SIX_MONTHS, THRESHOLDS, 100, None, {}
    )

    assert recommendation.technical_vote[Direction.BUY] == pytest.approx(7.6)


# --- substitution in the aggregate -----------------------------------------


def test_external_verdict_replaces_the_local_technical_vote() -> None:
    verdict = verdict_from_external(_external_payload(action="sell", priceState="BREAKDOWN_ZONE"))
    signals = _local_technical_signals() + _non_technical_signals()

    recommendation = aggregate_recommendation(
        signals,
        Horizon.THREE_TO_SIX_MONTHS,
        THRESHOLDS,
        100,
        None,
        {},
        technical_verdict=verdict,
    )

    # Vincent says SELL; the local technicals said BUY and must not contribute.
    assert recommendation.technical_vote[Direction.SELL] == pytest.approx(7.6)
    assert recommendation.technical_vote[Direction.BUY] == 0.0
    assert recommendation.technical_source is TechnicalSource.EXTERNAL
    assert recommendation.technical_producer == "vincent-stock-decision-dashboard"


def test_local_technicals_are_reported_but_excluded_from_the_score() -> None:
    verdict = verdict_from_external(_external_payload(action="sell", priceState="BREAKDOWN_ZONE"))
    signals = _local_technical_signals() + _non_technical_signals()

    with_external = aggregate_recommendation(
        signals, Horizon.THREE_TO_SIX_MONTHS, THRESHOLDS, 100, None, {}, technical_verdict=verdict
    )
    local_only = aggregate_recommendation(
        signals, Horizon.THREE_TO_SIX_MONTHS, THRESHOLDS, 100, None, {}
    )

    assert with_external.weighted_score != local_only.weighted_score
    assert with_external.local_technical_direction is Direction.BUY


def test_substitution_is_not_averaging() -> None:
    verdict = verdict_from_external(_external_payload(action="sell", priceState="BREAKDOWN_ZONE"))

    recommendation = aggregate_recommendation(
        _local_technical_signals(),
        Horizon.THREE_TO_SIX_MONTHS,
        THRESHOLDS,
        100,
        None,
        {},
        technical_verdict=verdict,
    )

    # Only Vincent's technical remains, so the score is a clean -1, not a blend.
    assert recommendation.weighted_score == pytest.approx(-1.0)


def test_no_verdict_leaves_behavior_unchanged() -> None:
    signals = _local_technical_signals() + _non_technical_signals()

    baseline = aggregate_recommendation(signals, Horizon.ONE_WEEK, THRESHOLDS, 90, None, {})

    assert baseline.technical_source is TechnicalSource.LOCAL
    assert baseline.technical_producer is None
    assert baseline.technical_agreement is None


# --- agreement --------------------------------------------------------------


def test_agreement_is_true_when_both_engines_reach_the_same_direction() -> None:
    verdict = verdict_from_external(_external_payload(action="buy"))
    signals = _local_technical_signals() + _non_technical_signals()

    recommendation = aggregate_recommendation(
        signals, Horizon.THREE_TO_SIX_MONTHS, THRESHOLDS, 100, None, {}, technical_verdict=verdict
    )

    assert recommendation.technical_agreement is True


def test_agreement_is_false_when_the_engines_disagree() -> None:
    verdict = verdict_from_external(_external_payload(action="sell", priceState="BREAKDOWN_ZONE"))
    signals = _local_technical_signals() + _non_technical_signals()

    recommendation = aggregate_recommendation(
        signals, Horizon.THREE_TO_SIX_MONTHS, THRESHOLDS, 100, None, {}, technical_verdict=verdict
    )

    assert recommendation.technical_agreement is False


def test_pre_substituted_signals_are_not_substituted_twice() -> None:
    # analyze_symbol substitutes up front so the response can report the signals
    # actually voted on. The aggregator must not then add a second external signal.
    verdict = verdict_from_external(_external_payload(action="sell", priceState="BREAKDOWN_ZONE"))
    signals = _local_technical_signals() + _non_technical_signals()
    voting, displaced = substitute_technical_signals(signals, verdict)

    recommendation = aggregate_recommendation(
        voting,
        Horizon.THREE_TO_SIX_MONTHS,
        THRESHOLDS,
        100,
        None,
        {},
        technical_verdict=verdict,
        displaced_local_verdict=displaced,
    )

    assert recommendation.technical_vote[Direction.SELL] == pytest.approx(7.6)
    assert recommendation.technical_agreement is False
    assert recommendation.local_technical_direction is Direction.BUY


def test_pre_substituted_path_matches_the_inline_path() -> None:
    verdict = verdict_from_external(_external_payload(action="sell", priceState="BREAKDOWN_ZONE"))
    signals = _local_technical_signals() + _non_technical_signals()
    voting, displaced = substitute_technical_signals(signals, verdict)

    inline = aggregate_recommendation(
        signals, Horizon.THREE_TO_SIX_MONTHS, THRESHOLDS, 100, None, {}, technical_verdict=verdict
    )
    pre = aggregate_recommendation(
        voting,
        Horizon.THREE_TO_SIX_MONTHS,
        THRESHOLDS,
        100,
        None,
        {},
        technical_verdict=verdict,
        displaced_local_verdict=displaced,
    )

    assert inline.weighted_score == pre.weighted_score
    assert inline.technical_vote == pre.technical_vote
    assert inline.technical_agreement == pre.technical_agreement


def test_agreement_is_unknown_when_there_are_no_local_technicals() -> None:
    verdict = verdict_from_external(_external_payload())

    recommendation = aggregate_recommendation(
        _non_technical_signals(),
        Horizon.THREE_TO_SIX_MONTHS,
        THRESHOLDS,
        100,
        None,
        {},
        technical_verdict=verdict,
    )

    assert recommendation.technical_agreement is None


# --- per-horizon verdicts ----------------------------------------------------


def test_resolve_by_horizon_carries_each_horizon_independently() -> None:
    payloads = {
        Horizon.ONE_WEEK: _external_payload(action="buy", confidence=60),
        Horizon.TWO_TO_FOUR_WEEKS: _external_payload(action="hold", priceState="NEUTRAL_ZONE", confidence=50),
        Horizon.THREE_TO_SIX_MONTHS: _external_payload(action="sell", priceState="BREAKDOWN_ZONE", confidence=80),
    }

    resolved = resolve_technical_verdicts_by_horizon(payloads)

    by_horizon = {entry.horizon: entry.verdict for entry in resolved}
    assert set(by_horizon) == set(payloads)
    assert by_horizon[Horizon.ONE_WEEK].direction is Direction.BUY
    assert by_horizon[Horizon.TWO_TO_FOUR_WEEKS].direction is Direction.HOLD
    assert by_horizon[Horizon.THREE_TO_SIX_MONTHS].direction is Direction.SELL
    # None of the three moves toward a shared average.
    assert by_horizon[Horizon.ONE_WEEK].confidence == pytest.approx(0.60)
    assert by_horizon[Horizon.THREE_TO_SIX_MONTHS].confidence == pytest.approx(0.80)


def test_resolve_by_horizon_omits_a_horizon_missing_from_the_batch() -> None:
    payloads = {Horizon.ONE_WEEK: _external_payload()}

    resolved = resolve_technical_verdicts_by_horizon(payloads)

    assert [entry.horizon for entry in resolved] == [Horizon.ONE_WEEK]


def test_resolve_by_horizon_drops_an_invalid_payload_rather_than_failing_the_batch() -> None:
    payloads = {
        Horizon.ONE_WEEK: _external_payload(action="buy"),
        # SELL is illegal in an opportunity zone: this horizon must be dropped,
        # not defaulted, and must not take the other horizons down with it.
        Horizon.TWO_TO_FOUR_WEEKS: _external_payload(action="sell"),
        Horizon.THREE_TO_SIX_MONTHS: _external_payload(action="sell", priceState="BREAKDOWN_ZONE"),
    }

    resolved = resolve_technical_verdicts_by_horizon(payloads)

    assert {entry.horizon for entry in resolved} == {Horizon.ONE_WEEK, Horizon.THREE_TO_SIX_MONTHS}
