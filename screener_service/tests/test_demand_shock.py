from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

from shared.data_quality import FreshValue
from shared.enums import EntryAssessment, Freshness, MarketRegime, Universe
from shared.models import RegimeResponse, ScreenRequest

from screener_service.core.demand_shock import run_demand_shock_screen
from screener_service.core.fundamentals_bulk import MetricValue, ScreenerMetrics


def test_demand_shock_ranks_growth_leaders_first(monkeypatch) -> None:
    monkeypatch.setattr("screener_service.core.demand_shock.resolve_universe", lambda universe, tickers=None: FreshValue(["NVDA", "KO"], Freshness.LIVE, None))
    monkeypatch.setattr("screener_service.core.demand_shock.current_regime", _fake_regime)
    monkeypatch.setattr("screener_service.core.demand_shock.append_demand_shock_results", lambda response: None)
    monkeypatch.setattr("screener_service.core.demand_shock.fetch_entry", _fake_entry)
    monkeypatch.setattr(
        "screener_service.core.demand_shock.fetch_metrics",
        lambda symbols: {symbol: FreshValue(_metric_map()[symbol], Freshness.DELAYED, None) for symbol in symbols},
    )

    response = asyncio.run(
        run_demand_shock_screen(
            ScreenRequest(universe=Universe.SP500, limit=10, include_analysis=True, lookback_days=30),
        )
    )

    assert response.screen_type == "demand_shock"
    assert [item.symbol for item in response.results][:2] == ["NVDA", "KO"]
    assert response.results[0].opportunity_score > response.results[1].opportunity_score
    assert response.results[0].opportunity_score > 70
    assert response.results[0].entry_assessment == EntryAssessment.BUY_NOW.value
    assert response.results[0].revenue_accel_pct is not None
    assert response.results[0].analyst_upgrades_30d is not None
    assert response.results[0].margin_expansion_bps is not None


def test_demand_shock_handles_missing_analyst_data(monkeypatch) -> None:
    monkeypatch.setattr("screener_service.core.demand_shock.resolve_universe", lambda universe, tickers=None: FreshValue(["NEWIPO"], Freshness.LIVE, None))
    monkeypatch.setattr("screener_service.core.demand_shock.current_regime", _fake_regime)
    monkeypatch.setattr("screener_service.core.demand_shock.append_demand_shock_results", lambda response: None)
    monkeypatch.setattr(
        "screener_service.core.demand_shock.fetch_metrics",
        lambda symbols: {"NEWIPO": FreshValue(_missing_metric(), Freshness.DELAYED, None)},
    )

    response = asyncio.run(
        run_demand_shock_screen(
            ScreenRequest(universe=Universe.CUSTOM, tickers=["NEWIPO"], limit=5, include_analysis=False, lookback_days=30),
        )
    )

    assert response.results
    assert response.results[0].symbol == "NEWIPO"
    assert response.results[0].opportunity_score >= 0
    assert response.results[0].entry_assessment is None


def _metric_map() -> dict[str, ScreenerMetrics]:
    return {
        "NVDA": _metrics(
            "NVDA",
            price=100,
            market_cap=2_000_000_000_000,
            avg_volume=30_000_000,
            sector="Technology",
            self_5y_valuation_percentile=25,
            revenue_growth_yoy_pct=35,
            earnings_growth_yoy_pct=30,
            gross_margin_pct=70,
            operating_margin_pct=30,
            recommendation_mean=1.7,
            institutional_pct=80,
            insider_pct=4,
            short_percent_float=3,
            beta=1.1,
        ),
        "KO": _metrics(
            "KO",
            price=60,
            market_cap=250_000_000_000,
            avg_volume=12_000_000,
            sector="Consumer Staples",
            self_5y_valuation_percentile=80,
            revenue_growth_yoy_pct=3,
            earnings_growth_yoy_pct=2,
            gross_margin_pct=30,
            operating_margin_pct=8,
            recommendation_mean=3.5,
            institutional_pct=70,
            insider_pct=2,
            short_percent_float=6,
            beta=0.6,
        ),
    }


def _missing_metric() -> ScreenerMetrics:
    return _metrics(
        "NEWIPO",
        price=25,
        market_cap=2_500_000_000,
        avg_volume=1_000_000,
        sector="Technology",
        revenue_growth_yoy_pct=20,
        gross_margin_pct=55,
        operating_margin_pct=15,
        short_percent_float=8,
    )


def _metrics(symbol: str, **values: float | str) -> ScreenerMetrics:
    return ScreenerMetrics(
        symbol=symbol,
        values={key: MetricValue(value, Freshness.DELAYED, None) for key, value in values.items()},
    )


def _fake_regime() -> RegimeResponse:
    return RegimeResponse(
        market_regime=MarketRegime.NEUTRAL,
        generated_at=datetime.now(timezone.utc),
        data_freshness={"price": Freshness.DELAYED.value},
        data_quality_score=100,
        confidence=1,
        sector_leaders=["XLK"],
        sector_laggards=["XLP"],
        reason="test regime",
    )


async def _fake_entry(symbol: str, horizon):
    return SimpleNamespace(entry_assessment=EntryAssessment.BUY_NOW, ideal_buy_zone=(95.0, 105.0))
