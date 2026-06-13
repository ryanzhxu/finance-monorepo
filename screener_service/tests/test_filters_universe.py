from __future__ import annotations

from shared.enums import Freshness, Universe

from screener_service.core.filters import apply_filters
from screener_service.core.fundamentals_bulk import MetricValue, ScreenerMetrics
from screener_service.core.universe import resolve_universe


def test_custom_universe_uses_request_tickers() -> None:
    result = resolve_universe(Universe.CUSTOM, ["nvda", "KO", "nvda"])

    assert result.value == ["KO", "NVDA"]
    assert result.freshness == Freshness.LIVE


def test_filters_drop_low_market_cap_penny_and_otc() -> None:
    filters = {
        "min_market_cap_usd": 1_000_000_000,
        "min_avg_dollar_volume_usd": 5_000_000,
        "exclude_penny_stocks": True,
        "exclude_otc": True,
        "meme_behavior_guard": True,
    }
    keep = _metrics("KEEP", price=50, market_cap=2_000_000_000, avg_volume=200_000)
    penny = _metrics("PENNY", price=2, market_cap=2_000_000_000, avg_volume=10_000_000)
    small = _metrics("SMALL", price=20, market_cap=100_000_000, avg_volume=10_000_000)
    otc = _metrics("ABCDF", price=20, market_cap=2_000_000_000, avg_volume=10_000_000)

    kept, rejected = apply_filters([keep, penny, small, otc], filters)

    assert [item.symbol for item in kept] == ["KEEP"]
    assert rejected["PENNY"] == ["penny_stock"]
    assert rejected["SMALL"] == ["min_market_cap"]
    assert rejected["ABCDF"] == ["otc"]


def _metrics(symbol: str, **values: float | str) -> ScreenerMetrics:
    return ScreenerMetrics(
        symbol=symbol,
        values={key: MetricValue(value, Freshness.DELAYED, None) for key, value in values.items()},
    )
