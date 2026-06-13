from __future__ import annotations

from shared.enums import Direction, EntryAssessment, Horizon
from shared.models import Fundamentals, MacdBlock, Technicals

from analyst_service.core.entry_engine import compute_entry, decide_entry_assessment


RULES = {
    "ideal_zone_low_atr_multiple": 0.25,
    "ideal_zone_high_atr_multiple": 0.5,
    "breakout_buffer": 0.005,
    "breakout_volume_ratio": 1.5,
    "extension_threshold_pct": 10.0,
    "overbought_rsi": 75.0,
    "mild_strength_ma20_pct": 1.03,
    "aggressive_max_rsi": 60.0,
    "conservative_min_rsi": 35.0,
    "strong_trend_ma200_distance_pct": 5.0,
    "reasonable_pe_percentile": 65.0,
    "min_buy_now_risk_reward": 1.2,
}


def test_decision_table_buy_now_inside_zone() -> None:
    assessment = decide_entry_assessment(
        current_price=101,
        support1=100,
        resistance1=110,
        direction=Direction.BUY,
        is_overextended=False,
        trend_strong=False,
        rsi_14=42,
        inside_ideal_zone=True,
        consolidating_under_resistance=False,
        invalidation_breached=False,
        meme_behavior=False,
        fundamentals_strong=False,
        fundamentals_weak=False,
        valuation_reasonable=True,
        horizon=Horizon.TWO_TO_FOUR_WEEKS,
        risk_reward_ratio=2.0,
        min_buy_now_risk_reward=1.2,
    )

    assert assessment == EntryAssessment.BUY_NOW


def test_decision_table_wait_for_pullback_when_overextended() -> None:
    assessment = decide_entry_assessment(
        current_price=125,
        support1=100,
        resistance1=130,
        direction=Direction.BUY,
        is_overextended=True,
        trend_strong=True,
        rsi_14=80,
        inside_ideal_zone=False,
        consolidating_under_resistance=False,
        invalidation_breached=False,
        meme_behavior=False,
        fundamentals_strong=True,
        fundamentals_weak=False,
        valuation_reasonable=True,
        horizon=Horizon.THREE_TO_SIX_MONTHS,
        risk_reward_ratio=3.0,
        min_buy_now_risk_reward=1.2,
    )

    assert assessment == EntryAssessment.WAIT_FOR_PULLBACK


def test_compute_entry_levels_are_deterministic() -> None:
    technicals = Technicals(
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
        volume_ratio_90d=1.0,
        dist_from_ma20_pct=1.0,
        dist_from_ma200_pct=12.0,
    )
    fundamentals = Fundamentals(revenue_growth_yoy_pct=20, pe_percentile_5y=50)

    entry = compute_entry(101, technicals, fundamentals, Direction.BUY, Horizon.TWO_TO_FOUR_WEEKS, RULES)

    assert entry.ideal_buy_zone == (99.0, 102.0)
    assert entry.stop_loss_suggestion == 96.0
    assert entry.invalidation_level == 94.0
    assert entry.entry_assessment == EntryAssessment.BUY_NOW


def test_decision_table_waits_when_buy_zone_has_poor_risk_reward() -> None:
    assessment = decide_entry_assessment(
        current_price=108,
        support1=100,
        resistance1=110,
        direction=Direction.BUY,
        is_overextended=False,
        trend_strong=False,
        rsi_14=45,
        inside_ideal_zone=True,
        consolidating_under_resistance=False,
        invalidation_breached=False,
        meme_behavior=False,
        fundamentals_strong=False,
        fundamentals_weak=False,
        valuation_reasonable=True,
        horizon=Horizon.TWO_TO_FOUR_WEEKS,
        risk_reward_ratio=0.5,
        min_buy_now_risk_reward=1.2,
    )

    assert assessment == EntryAssessment.WAIT_FOR_PULLBACK
