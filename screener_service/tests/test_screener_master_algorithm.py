from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from shared.enums import Direction, EntryAssessment, Freshness, Horizon, MarketRegime, ScreenType, TrendQuality
from shared.models import (
    AnalyzeResponse,
    EntryBlock,
    Fundamentals,
    Macro,
    Recommendation,
    ScreenRequest,
    ScreenResultItem,
    Technicals,
    TrendingResultItem,
)

from screener_service.core.screening import _attach_buyability


def _screen_item(recommendation: Direction) -> ScreenResultItem:
    return ScreenResultItem(
        rank=1,
        symbol="AAA",
        screen_type=ScreenType.OPPORTUNITIES,
        opportunity_score=70.0,
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
        recommendation=recommendation,
    )


def _trend_result() -> TrendingResultItem:
    return TrendingResultItem(
        symbol="AAA",
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


def _analysis(direction: Direction) -> AnalyzeResponse:
    return AnalyzeResponse(
        symbol="AAA",
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
            entry_assessment=EntryAssessment.BUY_NOW,
            reason="entry",
        ),
        recommendation=Recommendation(
            direction=direction,
            confidence=0.8,
            signal_vote={Direction.BUY: 3, Direction.HOLD: 1, Direction.SELL: 0},
            weighted_score=0.5,
            horizon=Horizon.TWO_TO_FOUR_WEEKS,
            review_action="add_watch",
        ),
    )


def test_master_direction_confirms_when_it_matches_the_screen(monkeypatch) -> None:
    async def _fake_fetch_analysis(symbol: str, horizon) -> AnalyzeResponse:
        return _analysis(Direction.BUY)

    monkeypatch.setattr("screener_service.core.screening.fetch_analysis", _fake_fetch_analysis)
    item = _screen_item(Direction.BUY)
    trend_map = {"AAA": _trend_result()}

    asyncio.run(_attach_buyability([item], trend_map, ScreenRequest(tickers=["AAA"], horizon=Horizon.TWO_TO_FOUR_WEEKS)))

    assert item.master_direction == Direction.BUY
    assert item.master_confirms is True


def test_master_direction_reports_disagreement_rather_than_hiding_it(monkeypatch) -> None:
    async def _fake_fetch_analysis(symbol: str, horizon) -> AnalyzeResponse:
        return _analysis(Direction.SELL)

    monkeypatch.setattr("screener_service.core.screening.fetch_analysis", _fake_fetch_analysis)
    item = _screen_item(Direction.BUY)
    trend_map = {"AAA": _trend_result()}

    asyncio.run(_attach_buyability([item], trend_map, ScreenRequest(tickers=["AAA"], horizon=Horizon.TWO_TO_FOUR_WEEKS)))

    assert item.master_direction == Direction.SELL
    assert item.master_confirms is False


def test_master_direction_is_none_when_analysis_is_unavailable(monkeypatch) -> None:
    async def _missing_analysis(symbol: str, horizon) -> None:
        return None

    monkeypatch.setattr("screener_service.core.screening.fetch_analysis", _missing_analysis)
    item = _screen_item(Direction.BUY)
    trend_map = {"AAA": _trend_result()}

    asyncio.run(_attach_buyability([item], trend_map, ScreenRequest(tickers=["AAA"], horizon=Horizon.TWO_TO_FOUR_WEEKS)))

    assert item.master_direction is None
    assert item.master_confirms is None
