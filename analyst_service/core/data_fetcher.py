from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pandas as pd

from shared.data_quality import FreshValue, utc_now
from shared.enums import Freshness
from shared.models import Fundamentals, Macro, Sentiment


def _empty_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])


def _estimated_ohlcv(current_price: float | None) -> pd.DataFrame:
    if current_price is None:
        return _empty_frame()
    index = pd.bdate_range(end=pd.Timestamp.utcnow().normalize(), periods=260)
    close = pd.Series(float(current_price), index=index)
    return pd.DataFrame(
        {
            "open": close,
            "high": close,
            "low": close,
            "close": close,
            "volume": pd.Series(0.0, index=index),
        }
    )


def fetch_ohlcv(symbol: str, current_price: float | None = None) -> FreshValue[pd.DataFrame]:
    try:
        import yfinance as yf

        frame = yf.download(symbol, period="18mo", interval="1d", progress=False, auto_adjust=False)
        if isinstance(frame.columns, pd.MultiIndex):
            frame.columns = [column[0] for column in frame.columns]
        if frame.empty:
            estimated = _estimated_ohlcv(current_price)
            freshness = Freshness.ESTIMATED if not estimated.empty else Freshness.MISSING
            return FreshValue(estimated, freshness, utc_now() if not estimated.empty else None)
        frame = frame.rename(columns=str.lower)
        frame = frame.rename(columns={"adj close": "adj_close"})
        required = ["open", "high", "low", "close", "volume"]
        return FreshValue(frame[required].dropna(how="all"), Freshness.DELAYED, datetime.now(timezone.utc))
    except Exception:
        estimated = _estimated_ohlcv(current_price)
        freshness = Freshness.ESTIMATED if not estimated.empty else Freshness.MISSING
        return FreshValue(estimated, freshness, utc_now() if not estimated.empty else None)


def fetch_fundamentals(symbol: str) -> FreshValue[Fundamentals]:
    try:
        import yfinance as yf

        ticker = yf.Ticker(symbol)
        info: dict[str, Any] = ticker.info or {}
        revenue_growth = info.get("revenueGrowth")
        gross_margin = info.get("grossMargins")
        trailing_pe = info.get("trailingPE")
        pe_percentile = None
        if trailing_pe is not None:
            pe_percentile = max(0.0, min(100.0, 50.0 + (float(trailing_pe) - 20.0)))
        fundamentals = Fundamentals(
            eps_surprise_pct=None,
            pe_percentile_5y=pe_percentile,
            analyst_upgrades_30d=0,
            analyst_downgrades_30d=0,
            revenue_growth_yoy_pct=None if revenue_growth is None else round(float(revenue_growth) * 100, 2),
            fcf_trend=None,
            gross_margin_pct=None if gross_margin is None else round(float(gross_margin) * 100, 2),
        )
        return FreshValue(fundamentals, Freshness.QUARTERLY, datetime.now(timezone.utc))
    except Exception:
        return FreshValue(Fundamentals(), Freshness.MISSING, None)


def fetch_sentiment(symbol: str) -> FreshValue[Sentiment]:
    return FreshValue(Sentiment(), Freshness.MISSING, None)


def fetch_macro() -> FreshValue[Macro]:
    return FreshValue(Macro(), Freshness.MISSING, None)
