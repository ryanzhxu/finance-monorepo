from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from analyst_service.api.main import app
from analyst_service.api.routers import analysis as analysis_router
from shared.enums import Direction, EntryAssessment, Freshness, MarketRegime
from shared.models import AnalyzeResponse, EntryBlock, Fundamentals, Macro, Recommendation, Sentiment, Signal, Technicals, MacdBlock


def test_entry_route_includes_freshness_and_quality(monkeypatch) -> None:
    async def fake_analyze_symbol(request):
        return AnalyzeResponse(
            symbol=request.symbol,
            generated_at=datetime(2026, 6, 14, tzinfo=timezone.utc),
            data_freshness={"price": "last_close (2026-06-12)"},
            data_quality_score=100,
            confidence=0.5,
            technicals=Technicals(macd=MacdBlock(), support_levels=[100], resistance_levels=[110]),
            fundamentals=Fundamentals(),
            sentiment=Sentiment(),
            macro=Macro(market_regime=MarketRegime.NEUTRAL),
            signals=[Signal(dimension="RSI", signal=Direction.HOLD, weight=1.0, note="neutral")],
            entry=EntryBlock(
                current_price=101.0,
                ideal_buy_zone=(99.0, 101.0),
                aggressive_entry_price=101.0,
                conservative_entry_price=None,
                breakout_buy_level=110.55,
                support_levels=[100.0, 95.0],
                resistance_levels=[110.0, 120.0],
                stop_loss_suggestion=96.0,
                invalidation_level=95.0,
                risk_reward_ratio=1.25,
                is_overextended=False,
                breakout_volume_confirmed=False,
                entry_assessment=EntryAssessment.BUY_NOW,
                reason="Price near support.",
            ),
            recommendation=Recommendation(
                direction=Direction.BUY,
                confidence=0.5,
                signal_vote={Direction.BUY: 1},
                weighted_score=0.5,
                horizon=request.horizon,
                review_action="add_watch",
            ),
            narrative=None,
        )

    monkeypatch.setattr(analysis_router, "analyze_symbol", fake_analyze_symbol)

    client = TestClient(app)
    response = client.post("/entry", json={"symbol": "NVDA", "asset_type": "STOCK", "horizon": "2-4W"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["data_freshness"]["price"] == "last_close (2026-06-12)"
    assert payload["data_quality_score"] == 100
    assert payload["entry_assessment"] == EntryAssessment.BUY_NOW.value
