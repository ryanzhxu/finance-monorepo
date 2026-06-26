from __future__ import annotations

from shared.enums import Direction, EntryAssessment, Horizon
from shared.models import Fundamentals, MacdBlock, Technicals

from analyst_service.core.entry_engine import compute_entry


RULES = {
    "ideal_zone_low_atr_multiple": 0.25,
    "zone_atr_mult": 1.0,
    "ma20_proximity_atr_tolerance": 1.0,
    "breakout_buffer": 0.005,
    "breakout_volume_ratio": 1.5,
    "extension_threshold_pct": 10.0,
    "overbought_rsi": 75.0,
    "mild_strength_ma20_pct": 1.03,
    "aggressive_max_rsi": 60.0,
    "conservative_min_rsi": 35.0,
    "strong_trend_ma200_distance_pct": 5.0,
    "reasonable_pe_percentile": 65.0,
    "rr_min": 1.0,
}


def _base_technicals(*, volume_ratio_90d: float = 1.0) -> Technicals:
    return Technicals(
        rsi_14=42,
        macd=MacdBlock(),
        ma_20=101,
        ma_50=98,
        ma_200=90,
        support_levels=[100, 95],
        resistance_levels=[112, 120],
        atr_14=4,
        bb_upper=115,
        bb_lower=95,
        bb_mid=105,
        volume_ratio_90d=volume_ratio_90d,
        dist_from_ma20_pct=1.0,
        dist_from_ma200_pct=12.0,
    )


def test_buy_now_becomes_wait_for_pullback_in_risk_off() -> None:
    entry = compute_entry(
        101,
        _base_technicals(),
        Fundamentals(revenue_growth_yoy_pct=20, pe_percentile_5y=50),
        Direction.BUY,
        Horizon.TWO_TO_FOUR_WEEKS,
        RULES,
        regime="risk_off",
    )

    assert entry.entry_assessment == EntryAssessment.WAIT_FOR_PULLBACK
    assert entry.regime_override is True
    assert entry.regime_override_reason == "risk-off suppresses buy_now"


def test_buy_now_stays_buy_now_in_neutral() -> None:
    entry = compute_entry(
        101,
        _base_technicals(),
        Fundamentals(revenue_growth_yoy_pct=20, pe_percentile_5y=50),
        Direction.BUY,
        Horizon.TWO_TO_FOUR_WEEKS,
        RULES,
        regime="neutral",
    )

    assert entry.entry_assessment == EntryAssessment.BUY_NOW
    assert entry.regime_override is False
    assert entry.regime_override_reason is None


def test_avoid_stays_avoid_in_risk_off() -> None:
    entry = compute_entry(
        101,
        _base_technicals(),
        Fundamentals(revenue_growth_yoy_pct=20, pe_percentile_5y=50),
        Direction.SELL,
        Horizon.TWO_TO_FOUR_WEEKS,
        RULES,
        regime="risk_off",
    )

    assert entry.entry_assessment == EntryAssessment.AVOID
    assert entry.regime_override is False
    assert entry.regime_override_reason is None


def test_breakout_setup_becomes_avoid_in_risk_off() -> None:
    entry = compute_entry(
        109.0,
        _base_technicals(volume_ratio_90d=2.0),
        Fundamentals(revenue_growth_yoy_pct=20, pe_percentile_5y=50),
        Direction.BUY,
        Horizon.TWO_TO_FOUR_WEEKS,
        RULES,
        regime="risk_off",
    )

    assert entry.entry_assessment == EntryAssessment.AVOID
    assert entry.regime_override is True
    assert entry.regime_override_reason == "risk-off suppresses breakout trades"
