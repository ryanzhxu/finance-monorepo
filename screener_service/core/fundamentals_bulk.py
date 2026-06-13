from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from shared.data_quality import FreshValue
from shared.enums import Freshness


@dataclass(frozen=True)
class MetricValue:
    value: float | str | None
    freshness: Freshness
    as_of: datetime | None


@dataclass
class ScreenerMetrics:
    symbol: str
    values: dict[str, MetricValue] = field(default_factory=dict)

    def get_float(self, key: str) -> float | None:
        item = self.values.get(key)
        if item is None or item.value is None:
            return None
        try:
            return float(item.value)
        except (TypeError, ValueError):
            return None

    def get_str(self, key: str) -> str | None:
        item = self.values.get(key)
        return None if item is None or item.value is None else str(item.value)

    @property
    def avg_dollar_volume(self) -> float | None:
        price = self.get_float("price")
        volume = self.get_float("avg_volume")
        if price is None or volume is None:
            return None
        return price * volume

    @property
    def freshness_map(self) -> dict[str, Freshness]:
        mapping: dict[str, Freshness] = {
            "price": self.values.get("price", MetricValue(None, Freshness.MISSING, None)).freshness,
            "fundamentals": Freshness.MISSING,
            "valuation_history": self.values.get("self_5y_valuation_percentile", MetricValue(None, Freshness.MISSING, None)).freshness,
            "ratings": self.values.get("recommendation_mean", MetricValue(None, Freshness.MISSING, None)).freshness,
            "institutional": self.values.get("institutional_pct", MetricValue(None, Freshness.MISSING, None)).freshness,
            "insider": self.values.get("insider_pct", MetricValue(None, Freshness.MISSING, None)).freshness,
        }
        fundamental_keys = ["market_cap", "revenue_growth_yoy_pct", "gross_margin_pct", "operating_margin_pct", "debt_to_equity"]
        if any(self.values.get(key) and self.values[key].freshness != Freshness.MISSING for key in fundamental_keys):
            mapping["fundamentals"] = Freshness.QUARTERLY
        return mapping


def fetch_metrics(symbols: list[str]) -> dict[str, FreshValue[ScreenerMetrics]]:
    return {symbol: fetch_metric(symbol) for symbol in symbols}


def fetch_metric(symbol: str) -> FreshValue[ScreenerMetrics]:
    now = datetime.now(timezone.utc)
    try:
        import yfinance as yf

        ticker = yf.Ticker(symbol)
        info: dict[str, Any] = ticker.info or {}
        values: dict[str, MetricValue] = {}
        _put(values, "price", _float(info.get("currentPrice") or info.get("regularMarketPrice")), Freshness.DELAYED, now)
        _put(values, "market_cap", _float(info.get("marketCap")), Freshness.QUARTERLY, now)
        _put(values, "avg_volume", _float(info.get("averageVolume") or info.get("averageVolume10days")), Freshness.DELAYED, now)
        _put(values, "sector", info.get("sector"), Freshness.QUARTERLY, now)
        _put(values, "trailing_pe", _float(info.get("trailingPE")), Freshness.QUARTERLY, now)
        _put(values, "forward_pe", _float(info.get("forwardPE")), Freshness.ESTIMATED, now)
        _put(values, "price_to_book", _float(info.get("priceToBook")), Freshness.QUARTERLY, now)
        _put(values, "price_to_sales", _float(info.get("priceToSalesTrailing12Months")), Freshness.QUARTERLY, now)
        _put(values, "enterprise_to_ebitda", _float(info.get("enterpriseToEbitda")), Freshness.QUARTERLY, now)
        _put(values, "revenue_growth_yoy_pct", _pct(info.get("revenueGrowth")), Freshness.QUARTERLY, now)
        _put(values, "earnings_growth_yoy_pct", _pct(info.get("earningsGrowth")), Freshness.QUARTERLY, now)
        _put(values, "gross_margin_pct", _pct(info.get("grossMargins")), Freshness.QUARTERLY, now)
        _put(values, "operating_margin_pct", _pct(info.get("operatingMargins")), Freshness.QUARTERLY, now)
        _put(values, "return_on_equity_pct", _pct(info.get("returnOnEquity")), Freshness.QUARTERLY, now)
        _put(values, "debt_to_equity", _float(info.get("debtToEquity")), Freshness.QUARTERLY, now)
        _put(values, "free_cashflow", _float(info.get("freeCashflow")), Freshness.QUARTERLY, now)
        _put(values, "total_cash", _float(info.get("totalCash")), Freshness.QUARTERLY, now)
        _put(values, "beta", _float(info.get("beta")), Freshness.QUARTERLY, now)
        _put(values, "short_percent_float", _pct(info.get("shortPercentOfFloat")), Freshness.DELAYED, now)
        _put(values, "recommendation_mean", _float(info.get("recommendationMean")), Freshness.ESTIMATED, now)
        _put(values, "fifty_day_average", _float(info.get("fiftyDayAverage")), Freshness.DELAYED, now)
        _put(values, "two_hundred_day_average", _float(info.get("twoHundredDayAverage")), Freshness.DELAYED, now)
        _put(values, "institutional_pct", _pct(info.get("heldPercentInstitutions")), Freshness.DELAYED, now)
        _put(values, "insider_pct", _pct(info.get("heldPercentInsiders")), Freshness.DELAYED, now)
        _put(values, "earnings_timestamp", _float(info.get("earningsTimestamp")), Freshness.ESTIMATED, now)
        _attach_valuation_history(ticker, values, now)
        metrics = ScreenerMetrics(symbol=symbol, values=values)
        freshness = Freshness.MISSING if metrics.get_float("price") is None and metrics.get_float("market_cap") is None else Freshness.DELAYED
        return FreshValue(metrics, freshness, now if freshness != Freshness.MISSING else None)
    except Exception:
        return FreshValue(ScreenerMetrics(symbol=symbol), Freshness.MISSING, None)


def _attach_valuation_history(ticker: object, values: dict[str, MetricValue], now: datetime) -> None:
    try:
        history = ticker.history(period="5y", interval="1mo", auto_adjust=True)
        if history.empty:
            _put(values, "self_5y_valuation_percentile", None, Freshness.MISSING, None)
            return
        close = _series(history, "Close")
        current = values.get("price")
        current_price = None if current is None or current.value is None else float(current.value)
        if current_price is None:
            _put(values, "self_5y_valuation_percentile", None, Freshness.MISSING, None)
            return
        percentile = float((close <= current_price).mean() * 100)
        _put(values, "self_5y_valuation_percentile", percentile, Freshness.DELAYED, now)
    except Exception:
        _put(values, "self_5y_valuation_percentile", None, Freshness.MISSING, None)


def _series(frame: pd.DataFrame, preferred: str) -> pd.Series:
    if preferred in frame:
        return frame[preferred].dropna()
    return frame.iloc[:, 0].dropna()


def _put(values: dict[str, MetricValue], key: str, value: float | str | None, freshness: Freshness, as_of: datetime | None) -> None:
    if value is None:
        values[key] = MetricValue(None, Freshness.MISSING, None)
    else:
        values[key] = MetricValue(value, freshness, as_of)


def _float(value: object) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _pct(value: object) -> float | None:
    parsed = _float(value)
    return None if parsed is None else parsed * 100
