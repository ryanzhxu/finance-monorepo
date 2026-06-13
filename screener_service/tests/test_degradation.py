from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from shared.data_quality import FreshValue
from shared.enums import Freshness, MarketRegime, ScreenType, Universe
from shared.models import RegimeResponse, ScreenRequest

from screener_service.core.fundamentals_bulk import MetricValue, ScreenerMetrics
from screener_service.core.screening import run_screen


def test_screen_degrades_when_analyst_is_down(monkeypatch) -> None:
    metrics = ScreenerMetrics(
        symbol="AAA",
        values={
            "price": MetricValue(100, Freshness.DELAYED, None),
            "market_cap": MetricValue(10_000_000_000, Freshness.QUARTERLY, None),
            "avg_volume": MetricValue(1_000_000, Freshness.DELAYED, None),
            "sector": MetricValue("Technology", Freshness.QUARTERLY, None),
            "self_5y_valuation_percentile": MetricValue(20, Freshness.DELAYED, None),
            "forward_pe": MetricValue(20, Freshness.ESTIMATED, None),
            "gross_margin_pct": MetricValue(65, Freshness.QUARTERLY, None),
            "revenue_growth_yoy_pct": MetricValue(20, Freshness.QUARTERLY, None),
        },
    )
    monkeypatch.setattr("screener_service.core.screening.resolve_universe", lambda universe, tickers=None: FreshValue(["AAA"], Freshness.LIVE, None))
    monkeypatch.setattr("screener_service.core.screening.fetch_metrics", lambda symbols: {"AAA": FreshValue(metrics, Freshness.DELAYED, None)})
    monkeypatch.setattr("screener_service.core.screening.current_regime", _fake_regime)
    monkeypatch.setattr("screener_service.core.screening.fetch_entry", _missing_entry)
    monkeypatch.setattr("screener_service.core.screening.append_screen_results", lambda response: None)

    response = asyncio.run(
        run_screen(
            ScreenRequest(universe=Universe.CUSTOM, tickers=["AAA"], include_analysis=True),
            ScreenType.OPPORTUNITIES,
        )
    )

    assert response.results
    assert response.results[0].entry_assessment is None
    assert "low_data_quality" in response.results[0].risk_flags
    assert "Analyst entry unavailable" in response.results[0].reason


async def _missing_entry(symbol, horizon):
    return None


def _fake_regime() -> RegimeResponse:
    return RegimeResponse(
        market_regime=MarketRegime.NEUTRAL,
        generated_at=datetime.now(timezone.utc),
        data_freshness={"price": Freshness.DELAYED.value},
        data_quality_score=100,
        confidence=1,
        sector_leaders=["XLK"],
        sector_laggards=["XLU"],
        reason="test regime",
    )
