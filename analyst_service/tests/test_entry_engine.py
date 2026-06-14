from __future__ import annotations

from shared.enums import Direction, EntryAssessment, Horizon
from shared.models import Fundamentals, MacdBlock, Technicals

from analyst_service.core.entry_engine import compute_entry, decide_entry_assessment


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
        rr_min=1.0,
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
        rr_min=1.0,
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

    assert entry.ideal_buy_zone == (99.0, 104.0)
    assert entry.stop_loss_suggestion == 96.0
    assert entry.invalidation_level == 94.0
    assert entry.entry_assessment == EntryAssessment.BUY_NOW
    assert entry.aggressive_entry_price == 101.0


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
        rr_min=1.0,
    )

    assert assessment == EntryAssessment.WAIT_FOR_PULLBACK


def test_wait_for_pullback_populates_conservative_entry_near_support() -> None:
    technicals = Technicals(
        rsi_14=45,
        macd=MacdBlock(),
        ma_20=214.62,
        ma_50=206.91,
        ma_200=189.26,
        support_levels=[199.34, 178.91],
        resistance_levels=[212.19, 232.28],
        atr_14=8.03,
        bb_upper=229.18,
        bb_lower=200.06,
        bb_mid=214.62,
        volume_ratio_90d=0.65,
        dist_from_ma20_pct=-4.39,
        dist_from_ma200_pct=8.42,
    )
    fundamentals = Fundamentals(revenue_growth_yoy_pct=20, pe_percentile_5y=50)

    entry = compute_entry(205.19, technicals, fundamentals, Direction.BUY, Horizon.TWO_TO_FOUR_WEEKS, RULES)

    assert entry.entry_assessment == EntryAssessment.WAIT_FOR_PULLBACK
    assert entry.risk_reward_ratio is not None and entry.risk_reward_ratio < RULES["rr_min"]
    assert entry.conservative_entry_price is not None
    assert abs(entry.conservative_entry_price - 199.34) < 0.05
    assert "R/R" in entry.reason
    assert "minimum 1.00" in entry.reason


def test_ideal_buy_zone_does_not_extend_to_far_ma20() -> None:
    technicals = Technicals(
        rsi_14=42,
        macd=MacdBlock(),
        ma_20=110,
        ma_50=98,
        ma_200=90,
        support_levels=[100, 95],
        resistance_levels=[120, 128],
        atr_14=2,
        bb_upper=115,
        bb_lower=95,
        bb_mid=105,
        volume_ratio_90d=1.0,
        dist_from_ma20_pct=1.0,
        dist_from_ma200_pct=12.0,
    )
    fundamentals = Fundamentals(revenue_growth_yoy_pct=20, pe_percentile_5y=50)

    entry = compute_entry(101, technicals, fundamentals, Direction.BUY, Horizon.TWO_TO_FOUR_WEEKS, RULES)

    assert entry.ideal_buy_zone == (99.5, 102.0)


def test_inside_zone_never_waits_for_pullback() -> None:
    technicals = Technicals(
        rsi_14=42,
        macd=MacdBlock(),
        ma_20=100.5,
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

    assert entry.current_price >= entry.ideal_buy_zone[0]
    assert entry.current_price <= entry.ideal_buy_zone[1]
    assert entry.entry_assessment != EntryAssessment.WAIT_FOR_PULLBACK
