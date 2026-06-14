from __future__ import annotations

from typing import Any

from shared.data_quality import compute_data_quality
from shared.enums import EntryAssessment, FundamentalState, TechnicalState, TrendQuality
from shared.models import AnalyzeResponse, BuyabilityResult, ScreenResultItem, TrendingResultItem


def assess_buyability(
    symbol: str,
    trend_result: TrendingResultItem,
    screen_result: ScreenResultItem | None,
    analysis: AnalyzeResponse | None,
) -> BuyabilityResult:
    if analysis is None:
        quality = max(0, trend_result.data_quality_score - 10)
        return BuyabilityResult(
            symbol=symbol,
            trend_score=float(trend_result.score_breakdown["trend_score"]),
            sentiment_score=trend_result.sentiment_score,
            technical_state=TechnicalState.NEUTRAL,
            fundamental_state=_fundamental_state_from_screen(screen_result),
            entry_assessment=None,
            ideal_buy_zone=None,
            current_price=None,
            data_quality_score=quality,
            confidence=round(trend_result.confidence * 0.85, 4),
            reason="Analyst unavailable; trend and sentiment available but technical confirmation is missing.",
            risk_flags=sorted(set([*trend_result.risk_flags, "low_data_quality"])),
        )

    technical_state = _technical_state(analysis)
    fundamental_state = _fundamental_state(analysis, screen_result)
    assessment = _decision_table(_trend_quality(trend_result.trend_quality), fundamental_state, technical_state, analysis)
    reason = _reason(trend_result.trend_quality, fundamental_state, technical_state, assessment, analysis)
    return BuyabilityResult(
        symbol=symbol,
        trend_score=float(trend_result.score_breakdown["trend_score"]),
        sentiment_score=trend_result.sentiment_score,
        technical_state=technical_state,
        fundamental_state=fundamental_state,
        entry_assessment=assessment,
        ideal_buy_zone=analysis.entry.ideal_buy_zone if analysis.entry else None,
        current_price=analysis.entry.current_price if analysis.entry else None,
        data_quality_score=min(100, round((trend_result.data_quality_score + analysis.data_quality_score) / 2)),
        confidence=round(min(trend_result.confidence, analysis.confidence), 4),
        reason=reason,
        risk_flags=sorted(set([*trend_result.risk_flags, *analysis.recommendation.risk_flags])),
    )


def _technical_state(analysis: AnalyzeResponse) -> TechnicalState:
    if analysis.entry and analysis.entry.is_overextended:
        return TechnicalState.OVEREXTENDED
    if analysis.technicals.breakout_state == "breakout" and analysis.entry and analysis.entry.breakout_volume_confirmed:
        return TechnicalState.BREAKOUT
    if analysis.technicals.rsi_14 is not None and analysis.technicals.rsi_14 < 35:
        return TechnicalState.OVERSOLD
    if analysis.technicals.dist_from_ma20_pct is not None and analysis.technicals.dist_from_ma20_pct > 5:
        return TechnicalState.EXTENDED
    return TechnicalState.NEUTRAL


def _fundamental_state(analysis: AnalyzeResponse, screen_result: ScreenResultItem | None) -> FundamentalState:
    if screen_result is not None:
        return _fundamental_state_from_screen(screen_result)
    strength = [
        analysis.fundamentals.revenue_growth_yoy_pct or 0.0,
        analysis.fundamentals.gross_margin_pct or 0.0,
        100 - (analysis.fundamentals.pe_percentile_5y or 50.0),
    ]
    score = sum(strength) / len(strength)
    if score >= 65:
        return FundamentalState.STRONG
    if score <= 45:
        return FundamentalState.WEAK
    return FundamentalState.MIXED


def _fundamental_state_from_screen(screen_result: ScreenResultItem | None) -> FundamentalState:
    if screen_result is None:
        return FundamentalState.MIXED
    if screen_result.growth_score >= 60 and screen_result.quality_score >= 65 and screen_result.valuation_score >= 45:
        return FundamentalState.STRONG
    if screen_result.growth_score < 40 or screen_result.quality_score < 45:
        return FundamentalState.WEAK
    return FundamentalState.MIXED


def _decision_table(
    trend_quality: TrendQuality,
    fundamental_state: FundamentalState,
    technical_state: TechnicalState,
    analysis: AnalyzeResponse,
) -> EntryAssessment:
    strong_trend = trend_quality in {TrendQuality.HIGH_QUALITY, TrendQuality.NEWS_DRIVEN, TrendQuality.EARNINGS_DRIVEN}
    meme_trend = trend_quality in {TrendQuality.MEME_FOMO, TrendQuality.PUMP_RISK}
    not_extended = technical_state in {TechnicalState.NEUTRAL, TechnicalState.OVERSOLD}
    if strong_trend and fundamental_state == FundamentalState.STRONG and technical_state == TechnicalState.OVEREXTENDED:
        return EntryAssessment.WAIT_FOR_PULLBACK
    if meme_trend and fundamental_state == FundamentalState.WEAK:
        return EntryAssessment.AVOID
    if trend_quality == TrendQuality.EARLY_ACCUMULATION and fundamental_state == FundamentalState.STRONG and not_extended:
        return EntryAssessment.LONG_TERM_CANDIDATE
    if fundamental_state == FundamentalState.STRONG and technical_state == TechnicalState.BREAKOUT:
        return EntryAssessment.WAIT_FOR_BREAKOUT
    if strong_trend and fundamental_state == FundamentalState.MIXED and not_extended:
        return EntryAssessment.SHORT_TERM_TRADE_ONLY
    if technical_state == TechnicalState.OVEREXTENDED:
        return EntryAssessment.WAIT_FOR_PULLBACK
    return analysis.entry.entry_assessment if analysis.entry else EntryAssessment.WAIT_FOR_PULLBACK


def _reason(
    trend_quality: TrendQuality | str,
    fundamental_state: FundamentalState,
    technical_state: TechnicalState,
    assessment: EntryAssessment,
    analysis: AnalyzeResponse,
) -> str:
    current_price = analysis.entry.current_price if analysis.entry else None
    price_text = f" at ${current_price:.2f}" if current_price is not None else ""
    return (
        f"Trend {_trend_quality(trend_quality).value}, fundamentals {fundamental_state.value}, "
        f"technicals {technical_state.value}{price_text}; entry maps to {assessment.value}."
    )


def _trend_quality(value: TrendQuality | str) -> TrendQuality:
    return value if isinstance(value, TrendQuality) else TrendQuality(str(value))
