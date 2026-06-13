from __future__ import annotations

from typing import Any

from shared.enums import Direction, EntryAssessment, Horizon
from shared.models import EntryBlock, Fundamentals, Technicals


def _round(value: float | None) -> float | None:
    return None if value is None else round(float(value), 2)


def _first_or(value: list[float], fallback: float) -> float:
    return float(value[0]) if value else fallback


def decide_entry_assessment(
    *,
    current_price: float,
    support1: float,
    resistance1: float,
    direction: Direction,
    is_overextended: bool,
    trend_strong: bool,
    rsi_14: float | None,
    inside_ideal_zone: bool,
    consolidating_under_resistance: bool,
    invalidation_breached: bool,
    meme_behavior: bool,
    fundamentals_strong: bool,
    fundamentals_weak: bool,
    valuation_reasonable: bool,
    horizon: Horizon,
    risk_reward_ratio: float | None = None,
    min_buy_now_risk_reward: float = 1.2,
) -> EntryAssessment:
    if is_overextended and trend_strong:
        return EntryAssessment.WAIT_FOR_PULLBACK
    if current_price < support1 and (rsi_14 or 50) < 30 and direction != Direction.SELL:
        return EntryAssessment.BUY_NOW
    if consolidating_under_resistance:
        return EntryAssessment.WAIT_FOR_BREAKOUT
    if inside_ideal_zone and not is_overextended and (risk_reward_ratio is None or risk_reward_ratio >= min_buy_now_risk_reward):
        return EntryAssessment.BUY_NOW
    if direction == Direction.SELL or invalidation_breached or meme_behavior:
        return EntryAssessment.AVOID
    if trend_strong and fundamentals_weak:
        return EntryAssessment.SHORT_TERM_TRADE_ONLY
    if fundamentals_strong and valuation_reasonable and horizon == Horizon.THREE_TO_SIX_MONTHS:
        return EntryAssessment.LONG_TERM_CANDIDATE
    return EntryAssessment.WAIT_FOR_PULLBACK


def compute_entry(
    current_price: float,
    technicals: Technicals,
    fundamentals: Fundamentals,
    direction: Direction,
    horizon: Horizon,
    rules: dict[str, Any],
    risk_flags: list[str] | None = None,
) -> EntryBlock:
    atr = float(technicals.atr_14 or max(current_price * 0.02, 0.01))
    support_levels = technicals.support_levels or [round(current_price - atr, 2), round(current_price - (2 * atr), 2)]
    resistance_levels = technicals.resistance_levels or [round(current_price + atr, 2), round(current_price + (2 * atr), 2)]
    support1 = _first_or(support_levels, current_price - atr)
    support2 = support_levels[1] if len(support_levels) > 1 else support1 - atr
    resistance1 = _first_or(resistance_levels, current_price + atr)
    ma20 = technicals.ma_20 or current_price
    ma50 = technicals.ma_50 or current_price
    rsi_14 = technicals.rsi_14

    ideal_low = support1 - (rules["ideal_zone_low_atr_multiple"] * atr)
    ideal_high = max(support1 + (rules["ideal_zone_high_atr_multiple"] * atr), ma20)
    is_overextended = bool(
        (technicals.dist_from_ma20_pct is not None and technicals.dist_from_ma20_pct > rules["extension_threshold_pct"])
        or (technicals.bb_upper is not None and current_price > technicals.bb_upper)
        or ((rsi_14 or 0) > rules["overbought_rsi"])
    )
    aggressive_entry = current_price if current_price <= ma20 * rules["mild_strength_ma20_pct"] and (rsi_14 or 50) < rules["aggressive_max_rsi"] else None
    conservative_entry = support1 if (rsi_14 or 50) > rules["conservative_min_rsi"] and current_price >= ma20 else None
    breakout_buy_level = resistance1 * (1 + rules["breakout_buffer"])
    breakout_volume_confirmed = bool((technicals.volume_ratio_90d or 0) >= rules["breakout_volume_ratio"])
    stop_loss = support1 - atr
    invalidation_level = min(support2, ma50 - atr)
    entry_for_rr = aggressive_entry or conservative_entry or current_price
    denominator = entry_for_rr - stop_loss
    risk_reward = None if denominator <= 0 else (resistance1 - entry_for_rr) / denominator
    trend_strong = bool((technicals.dist_from_ma200_pct or 0) >= rules["strong_trend_ma200_distance_pct"] and (technicals.ma_50 or 0) >= (technicals.ma_200 or 0))
    inside_zone = ideal_low <= current_price <= ideal_high
    consolidating = current_price < resistance1 and ((resistance1 - current_price) / resistance1) <= 0.03 and breakout_volume_confirmed
    fundamentals_strong = bool(
        (fundamentals.revenue_growth_yoy_pct or 0) > 10
        or (fundamentals.eps_surprise_pct or 0) > 5
        or fundamentals.fcf_trend == "rising"
    )
    fundamentals_weak = bool((fundamentals.revenue_growth_yoy_pct or 0) < -5 or (fundamentals.eps_surprise_pct or 0) < -5)
    valuation_reasonable = fundamentals.pe_percentile_5y is None or fundamentals.pe_percentile_5y <= rules["reasonable_pe_percentile"]
    assessment = decide_entry_assessment(
        current_price=current_price,
        support1=support1,
        resistance1=resistance1,
        direction=direction,
        is_overextended=is_overextended,
        trend_strong=trend_strong,
        rsi_14=rsi_14,
        inside_ideal_zone=inside_zone,
        consolidating_under_resistance=consolidating,
        invalidation_breached=current_price < invalidation_level,
        meme_behavior="meme_behavior" in (risk_flags or []),
        fundamentals_strong=fundamentals_strong,
        fundamentals_weak=fundamentals_weak,
        valuation_reasonable=valuation_reasonable,
        horizon=horizon,
        risk_reward_ratio=risk_reward,
        min_buy_now_risk_reward=rules["min_buy_now_risk_reward"],
    )
    reason = _reason(assessment, current_price, support1, resistance1, rsi_14, risk_reward, is_overextended)
    return EntryBlock(
        current_price=_round(current_price) or current_price,
        ideal_buy_zone=(_round(ideal_low) or ideal_low, _round(ideal_high) or ideal_high),
        aggressive_entry_price=_round(aggressive_entry),
        conservative_entry_price=_round(conservative_entry),
        breakout_buy_level=_round(breakout_buy_level),
        support_levels=[_round(level) or level for level in support_levels],
        resistance_levels=[_round(level) or level for level in resistance_levels],
        stop_loss_suggestion=_round(stop_loss) or stop_loss,
        invalidation_level=_round(invalidation_level) or invalidation_level,
        risk_reward_ratio=None if risk_reward is None else round(float(risk_reward), 2),
        is_overextended=is_overextended,
        breakout_volume_confirmed=breakout_volume_confirmed,
        entry_assessment=assessment,
        reason=reason,
    )


def _reason(
    assessment: EntryAssessment,
    current_price: float,
    support1: float,
    resistance1: float,
    rsi_14: float | None,
    risk_reward: float | None,
    is_overextended: bool,
) -> str:
    if assessment == EntryAssessment.BUY_NOW:
        return f"Price near ${support1:.2f} support; RSI {(rsi_14 or 50):.0f}; R/R {risk_reward:.2f}." if risk_reward else f"Price near ${support1:.2f} support; RSI {(rsi_14 or 50):.0f}."
    if assessment == EntryAssessment.WAIT_FOR_BREAKOUT:
        return f"Price is consolidating below ${resistance1:.2f}; wait for confirmed breakout volume."
    if assessment == EntryAssessment.AVOID:
        return "Directional signal, invalidation, or risk flags argue against a new entry."
    if assessment == EntryAssessment.SHORT_TERM_TRADE_ONLY:
        return "Trend is strong but fundamentals are weak; treat as short-term only."
    if assessment == EntryAssessment.LONG_TERM_CANDIDATE:
        return "Fundamentals are strong and valuation is reasonable for a longer horizon."
    if is_overextended:
        return "Price is extended versus trend bands; wait for a pullback toward support."
    return f"Wait for a pullback closer to ${support1:.2f} support before entry."
