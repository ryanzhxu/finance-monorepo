from __future__ import annotations

from datetime import date, datetime, timezone

from analyst_service.core.event_context import (
    ContextObservation,
    ContextStatus,
    evaluate_event_context,
)
from backtesting.event_library import EventType, ProvenanceStatus, load_event_fixtures
from shared.enums import Freshness, MarketRegime


def _verified_event(index: int = 0):
    event = load_event_fixtures()[index]
    evidence = [
        item.model_copy(
            update={
                "retrieved_at": datetime.combine(event.start_date, datetime.min.time(), tzinfo=timezone.utc)
            }
        )
        for item in event.evidence
    ]
    return event.model_copy(
        update={"evidence": evidence, "provenance_status": ProvenanceStatus.VERIFIED}
    )


def test_verified_event_context_emits_bounded_flags_and_evidence() -> None:
    event = _verified_event()
    result = evaluate_event_context(
        ContextObservation(
            symbol="SPY",
            as_of=date(2008, 6, 1),
            freshness=Freshness.LAST_CLOSE,
            volatility_pct=35.0,
            drawdown_pct=-12.0,
            gap_pct=-1.0,
            volume_ratio=2.4,
            macro_regime=MarketRegime.RISK_OFF,
        ),
        [event],
    )

    assert result.status == ContextStatus.AVAILABLE
    assert result.matched_event_ids == (event.event_id,)
    assert result.risk_flags == ("liquidity_stress", "macro_event_window")
    assert result.evidence[0].source_urls
    assert "BUY" not in result.model_dump_json()


def test_unverified_or_future_event_fails_closed_to_unknown() -> None:
    event = _verified_event()
    observation = ContextObservation(
        symbol="AAPL",
        as_of=date(2007, 1, 1),
        freshness=Freshness.LAST_CLOSE,
    )

    result = evaluate_event_context(observation, [event])

    assert result.status == ContextStatus.UNKNOWN
    assert result.matched_event_ids == ()
    assert result.unknowns == ("no_verified_event_match",)


def test_stale_observation_emits_stale_flag_without_event_match() -> None:
    result = evaluate_event_context(
        ContextObservation(
            symbol="NVDA",
            as_of=date(2026, 8, 4),
            freshness=Freshness.STALE,
            gap_pct=-8.0,
        ),
        [_verified_event()],
    )

    assert result.status == ContextStatus.UNKNOWN
    assert result.risk_flags == ("gap_risk", "stale_data")
    assert result.unknowns == ("observation_data_stale",)


def test_regulatory_event_adds_export_controls_risk_only_with_matching_context() -> None:
    event = _verified_event().model_copy(
        update={
            "event_id": "regulatory-export-shock",
            "event_type": EventType.REGULATORY_TRADE,
            "start_date": date(2026, 1, 1),
            "end_date": date(2026, 12, 31),
        }
    )
    result = evaluate_event_context(
        ContextObservation(symbol="NVDA", as_of=date(2026, 8, 4), freshness=Freshness.LAST_CLOSE),
        [event],
    )

    assert result.risk_flags == ("export_controls_risk",)


def test_context_evaluation_is_deterministic() -> None:
    observation = ContextObservation(
        symbol="SPY",
        as_of=date(2008, 6, 1),
        freshness=Freshness.LAST_CLOSE,
        volatility_pct=35.0,
        macro_regime=MarketRegime.RISK_OFF,
    )
    first = evaluate_event_context(observation, [_verified_event()])
    second = evaluate_event_context(observation, [_verified_event()])

    assert first == second
