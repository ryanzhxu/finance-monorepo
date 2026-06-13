from __future__ import annotations

from shared.enums import MarketRegime, ScreenType

from screener_service.core.fundamentals_bulk import MetricValue, ScreenerMetrics
from screener_service.core.scoring import score_universe
from shared.enums import Freshness


WEIGHTS = {
    "opportunity": {
        "valuation": 0.22,
        "growth": 0.16,
        "quality": 0.16,
        "momentum": 0.12,
        "analyst_revision": 0.10,
        "institutional_accumulation": 0.10,
        "insider_activity": 0.04,
        "risk": 0.10,
    },
    "regime_adjustments": {"risk_off": {}, "risk_on": {}},
    "thresholds": {"buy_score": 70, "sell_score": 40, "analyze_deeper_score": 70, "watch_score": 55},
}


def test_score_universe_ranks_stronger_candidate_first() -> None:
    strong = _metrics(
        "AAA",
        price=100,
        sector="Technology",
        self_5y_valuation_percentile=15,
        forward_pe=18,
        price_to_book=3,
        price_to_sales=4,
        enterprise_to_ebitda=12,
        revenue_growth_yoy_pct=30,
        earnings_growth_yoy_pct=25,
        gross_margin_pct=70,
        operating_margin_pct=30,
        return_on_equity_pct=25,
        debt_to_equity=40,
        free_cashflow=1_000_000_000,
        recommendation_mean=1.8,
        institutional_pct=80,
        insider_pct=6,
        beta=0.9,
        avg_volume=10_000_000,
        fifty_day_average=95,
        two_hundred_day_average=80,
    )
    weak = _metrics(
        "BBB",
        price=40,
        sector="Technology",
        self_5y_valuation_percentile=85,
        forward_pe=55,
        price_to_book=10,
        price_to_sales=16,
        enterprise_to_ebitda=32,
        revenue_growth_yoy_pct=-5,
        earnings_growth_yoy_pct=-10,
        gross_margin_pct=25,
        operating_margin_pct=2,
        return_on_equity_pct=2,
        debt_to_equity=220,
        free_cashflow=-10_000_000,
        recommendation_mean=3.8,
        institutional_pct=25,
        insider_pct=1,
        beta=1.8,
        avg_volume=8_000_000,
        fifty_day_average=45,
        two_hundred_day_average=48,
    )

    results = score_universe([weak, strong], WEIGHTS, ScreenType.OPPORTUNITIES, MarketRegime.NEUTRAL)

    assert [result.symbol for result in results] == ["AAA", "BBB"]
    assert results[0].rank == 1
    assert results[0].opportunity_score > results[1].opportunity_score
    assert "valuation" in results[0].score_breakdown
    assert "self_5y_valuation_percentile" in results[0].score_breakdown["valuation"]


def _metrics(symbol: str, **values: float | str) -> ScreenerMetrics:
    return ScreenerMetrics(
        symbol=symbol,
        values={key: MetricValue(value, Freshness.DELAYED, None) for key, value in values.items()},
    )
