from __future__ import annotations

from screener_service.core.fundamentals_bulk import ScreenerMetrics


def apply_filters(metrics: list[ScreenerMetrics], filters: dict[str, object]) -> tuple[list[ScreenerMetrics], dict[str, list[str]]]:
    kept: list[ScreenerMetrics] = []
    rejected: dict[str, list[str]] = {}
    for item in metrics:
        reasons: list[str] = []
        market_cap = item.get_float("market_cap")
        avg_dollar_volume = item.avg_dollar_volume
        price = item.get_float("price")
        symbol = item.symbol
        if market_cap is not None and market_cap < float(filters["min_market_cap_usd"]):
            reasons.append("min_market_cap")
        if avg_dollar_volume is not None and avg_dollar_volume < float(filters["min_avg_dollar_volume_usd"]):
            reasons.append("min_avg_dollar_volume")
        if bool(filters["exclude_penny_stocks"]) and price is not None and price < 5:
            reasons.append("penny_stock")
        if bool(filters["exclude_otc"]) and _looks_otc(symbol):
            reasons.append("otc")
        if reasons:
            rejected[symbol] = reasons
        else:
            kept.append(item)
    return kept, rejected


def _looks_otc(symbol: str) -> bool:
    return symbol.endswith("F") and len(symbol) >= 5
