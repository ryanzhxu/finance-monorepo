from __future__ import annotations

from datetime import date, datetime, timezone

from analyst_service.core.options_activity import (
    OptionQuote,
    OptionType,
    OptionsActivityResult,
    OptionsContextSignal,
    OptionsContextStatus,
    OptionsSnapshot,
    evaluate_options_activity,
)
from shared.enums import Freshness


def _snapshot(**changes) -> OptionsSnapshot:
    values = {
        "symbol": "nvda",
        "observed_at": datetime(2026, 8, 4, 12, tzinfo=timezone.utc),
        "retrieved_at": datetime(2026, 8, 4, 12, 1, tzinfo=timezone.utc),
        "freshness": Freshness.LIVE,
        "source": "fixture-options",
        "adjustment_mode": "unadjusted",
        "point_in_time_certified": True,
        "quotes": (
            OptionQuote(
                option_type=OptionType.CALL,
                expiry=date(2026, 9, 18),
                strike=180,
                volume=300,
                open_interest=150,
                bid=5.0,
                ask=5.5,
                implied_volatility=0.30,
            ),
            OptionQuote(
                option_type=OptionType.PUT,
                expiry=date(2026, 9, 18),
                strike=180,
                volume=100,
                open_interest=100,
                bid=4.5,
                ask=4.8,
                implied_volatility=0.28,
            ),
        ),
    }
    values.update(changes)
    return OptionsSnapshot(**values)


def test_normal_fixture_returns_bounded_informational_context() -> None:
    result = evaluate_options_activity(_snapshot(), historical_implied_volatility=(0.2, 0.25, 0.35, 0.4))

    assert result.status == OptionsContextStatus.AVAILABLE
    assert result.signal == OptionsContextSignal.CALL_DOMINANCE
    assert result.call_put_volume_ratio == 3.0
    assert result.call_put_open_interest_ratio == 1.5
    assert result.implied_volatility_percentile == 50.0
    assert result.signal_weight == 0.25
    assert "BUY" not in result.model_dump_json()
    assert "SELL" not in result.model_dump_json()


def test_illiquid_quotes_emit_a_risk_flag_without_provider_calls() -> None:
    result = evaluate_options_activity(
        _snapshot(
            quotes=(
                OptionQuote(
                    option_type=OptionType.CALL,
                    expiry=date(2026, 9, 18),
                    strike=180,
                    volume=10,
                    open_interest=100,
                    bid=0.1,
                    ask=0.5,
                ),
                OptionQuote(
                    option_type=OptionType.PUT,
                    expiry=date(2026, 9, 18),
                    strike=180,
                    volume=10,
                    open_interest=100,
                    bid=0.1,
                    ask=0.11,
                ),
            )
        )
    )

    assert result.status == OptionsContextStatus.AVAILABLE
    assert "options_liquidity" in result.risk_flags


def test_stale_snapshot_fails_closed_to_unknown() -> None:
    result = evaluate_options_activity(_snapshot(freshness=Freshness.STALE))

    assert result.status == OptionsContextStatus.UNKNOWN
    assert result.signal == OptionsContextSignal.UNKNOWN
    assert result.signal_weight == 0
    assert result.unknowns == ("options_data_stale",)


def test_contradictory_volume_and_open_interest_emits_no_signal() -> None:
    result = evaluate_options_activity(
        _snapshot(
            quotes=(
                OptionQuote(
                    option_type=OptionType.CALL,
                    expiry=date(2026, 9, 18),
                    strike=180,
                    volume=300,
                    open_interest=50,
                ),
                OptionQuote(
                    option_type=OptionType.PUT,
                    expiry=date(2026, 9, 18),
                    strike=180,
                    volume=100,
                    open_interest=200,
                ),
            )
        )
    )

    assert result.status == OptionsContextStatus.CONTRADICTORY
    assert result.signal == OptionsContextSignal.UNKNOWN
    assert result.signal_weight == 0
    assert "contradictory_activity" in result.unknowns


def test_options_evaluation_is_deterministic() -> None:
    first = evaluate_options_activity(_snapshot(), historical_implied_volatility=(0.2, 0.25, 0.35, 0.4))
    second = evaluate_options_activity(_snapshot(), historical_implied_volatility=(0.2, 0.25, 0.35, 0.4))

    assert isinstance(first, OptionsActivityResult)
    assert first == second
