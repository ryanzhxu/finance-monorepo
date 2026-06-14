from __future__ import annotations

from datetime import datetime, timezone

from shared.enums import Direction, EntryAssessment, Freshness, FundamentalState, Horizon, MarketRegime, TechnicalState, TrendQuality
from shared.models import AnalyzeResponse, BuyabilityResult, EntryBlock, Fundamentals, Macro, Recommendation, ScreenResultItem, Technicals, TrendingResultItem

from screener_service.core.buyability import _decision_table, assess_buyability


def test_buyability_decision_table_waits_on_strong_overextended_trend() -> None:
    assessment = _decision_table(
        TrendQuality.NEWS_DRIVEN,
        FundamentalState.STRONG,
        TechnicalState.OVEREXTENDED,
        _analysis(entry_assessment=EntryAssessment.BUY_NOW),
    )

    assert assessment == EntryAssessment.WAIT_FOR_PULLBACK


def test_buyability_decision_table_marks_early_accumulation_as_long_term() -> None:
    assessment = _decision_table(
        TrendQuality.EARLY_ACCUMULATION,
        FundamentalState.STRONG,
        TechnicalState.NEUTRAL,
        _analysis(entry_assessment=EntryAssessment.WAIT_FOR_PULLBACK),
    )

    assert assessment == EntryAssessment.LONG_TERM_CANDIDATE


def test_assess_buyability_returns_none_assessment_when_analyst_is_missing() -> None:
    trend = TrendingResultItem(
        symbol="NVDA",
        mention_count_24h=8,
        mention_count_3d=15,
        mention_count_5d=20,
        mention_growth_3d_pct=100.0,
        mention_growth_5d_pct=80.0,
        baseline_daily_mentions_30d=2.0,
        acceleration=3.0,
        sentiment_score=0.3,
        sentiment_change=0.1,
        pos_neu_neg_ratio=[0.6, 0.3, 0.1],
        retail_fomo_risk=15.0,
        news_catalyst="analyst_upgrade",
        trend_quality=TrendQuality.NEWS_DRIVEN,
        institutional_account_participation=0.3,
        data_freshness={"news": Freshness.DELAYED.value},
        data_quality_score=80,
        confidence=0.7,
        risk_flags=[],
        reason="trend",
        score_breakdown={"trend_score": 72.0},
    )
    screen = ScreenResultItem(
        rank=1,
        symbol="NVDA",
        screen_type="opportunities",
        opportunity_score=65.0,
        valuation_score=55.0,
        growth_score=70.0,
        quality_score=75.0,
        momentum_score=60.0,
        analyst_revision_score=65.0,
        institutional_accumulation_score=70.0,
        insider_activity_score=40.0,
        risk_score=25.0,
        score_breakdown={},
        data_freshness={"price": Freshness.DELAYED.value},
        data_quality_score=90,
        confidence=0.8,
        reason="screen",
        recommended_action="watch",
    )

    result = assess_buyability("NVDA", trend, screen, None)

    assert result.entry_assessment is None
    assert result.technical_state == TechnicalState.NEUTRAL
    assert "Analyst unavailable" in result.reason


def _analysis(entry_assessment: EntryAssessment) -> AnalyzeResponse:
    return AnalyzeResponse(
        symbol="NVDA",
        generated_at=datetime.now(timezone.utc),
        data_freshness={"price": Freshness.DELAYED.value},
        data_quality_score=90,
        confidence=0.8,
        technicals=Technicals(macd={"macd_line": 0, "signal_line": 0, "histogram": 0}, breakout_state="none", rsi_14=55, dist_from_ma20_pct=1.0),
        fundamentals=Fundamentals(revenue_growth_yoy_pct=20, gross_margin_pct=70, pe_percentile_5y=40),
        sentiment={},
        macro=Macro(market_regime=MarketRegime.NEUTRAL),
        signals=[],
        entry=EntryBlock(
            current_price=100.0,
            ideal_buy_zone=(95.0, 99.0),
            support_levels=[95.0],
            resistance_levels=[110.0],
            stop_loss_suggestion=92.0,
            invalidation_level=90.0,
            is_overextended=False,
            breakout_volume_confirmed=False,
            entry_assessment=entry_assessment,
            reason="entry",
        ),
        recommendation=Recommendation(
            direction=Direction.BUY,
            confidence=0.8,
            signal_vote={Direction.BUY: 3, Direction.HOLD: 1, Direction.SELL: 0},
            weighted_score=0.5,
            horizon=Horizon.TWO_TO_FOUR_WEEKS,
            review_action="add_watch",
        ),
    )
