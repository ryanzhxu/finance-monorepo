from __future__ import annotations

from datetime import date, datetime, time, timezone
import pandas as pd

from shared.data_quality import FreshValue, utc_now
from shared.enums import Freshness
from shared.models import Fundamentals, Macro, Sentiment
from shared.time_utils import (
    US_EASTERN,
    is_us_equity_market_open,
    latest_completed_us_equity_trading_day,
    previous_us_equity_trading_day,
)
from analyst_service.core.fundamentals import fetch_fundamentals as fetch_raw_fundamentals
from analyst_service.core.macro import fetch_macro as fetch_raw_macro
from analyst_service.core.sentiment import fetch_sentiment as fetch_raw_sentiment


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


def _frame_trading_date(frame: pd.DataFrame) -> date | None:
    if frame.empty:
        return None
    last_index = frame.index[-1]
    if isinstance(last_index, pd.Timestamp):
        return last_index.date()
    return pd.Timestamp(last_index).date()


def _close_timestamp(trading_date: date) -> datetime:
    return datetime.combine(trading_date, time(hour=16), tzinfo=US_EASTERN).astimezone(timezone.utc)


def classify_price_freshness(frame: pd.DataFrame, now: datetime | None = None) -> tuple[Freshness, datetime | None]:
    trading_date = _frame_trading_date(frame)
    if trading_date is None:
        return Freshness.MISSING, None

    observed_at = now or utc_now()
    if is_us_equity_market_open(observed_at):
        oldest_acceptable = previous_us_equity_trading_day(observed_at)
        if trading_date < oldest_acceptable:
            return Freshness.STALE, _close_timestamp(trading_date)
        return Freshness.DELAYED, observed_at

    latest_close = latest_completed_us_equity_trading_day(observed_at)
    if trading_date < latest_close:
        return Freshness.STALE, _close_timestamp(trading_date)
    return Freshness.LAST_CLOSE, _close_timestamp(trading_date)


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
        cleaned = frame[required].dropna(how="all")
        freshness, as_of = classify_price_freshness(cleaned)
        return FreshValue(cleaned, freshness, as_of)
    except Exception:
        estimated = _estimated_ohlcv(current_price)
        freshness = Freshness.ESTIMATED if not estimated.empty else Freshness.MISSING
        return FreshValue(estimated, freshness, utc_now() if not estimated.empty else None)


def fetch_fundamentals(symbol: str) -> FreshValue[Fundamentals]:
    raw = fetch_raw_fundamentals(symbol)
    fundamentals = Fundamentals(
        eps_surprise_pct=raw.eps_surprise_pct,
        pe_ratio=raw.pe_ratio,
        pb_ratio=raw.pb_ratio,
        ps_ratio=raw.ps_ratio,
        ev_ebitda=raw.ev_ebitda,
        pe_percentile_5y=raw.pe_percentile_5y,
        analyst_upgrades_30d=raw.analyst_upgrades_30d,
        analyst_downgrades_30d=raw.analyst_downgrades_30d,
        revenue_growth_yoy_pct=raw.revenue_growth_yoy_pct,
        fcf_trend=raw.fcf_trend,
        gross_margin_pct=raw.gross_margin_pct,
        freshness=raw.freshness,
        as_of=raw.as_of,
    )
    freshness = Freshness.QUARTERLY if raw.freshness == "quarterly" else Freshness.MISSING
    as_of = None
    if raw.as_of is not None:
        try:
            as_of = datetime.fromisoformat(raw.as_of).replace(tzinfo=timezone.utc)
        except ValueError:
            as_of = None
    return FreshValue(fundamentals, freshness, as_of)


def fetch_sentiment(symbol: str, price_history: pd.DataFrame | None = None) -> FreshValue[Sentiment]:
    raw = fetch_raw_sentiment(symbol, price_history=price_history)
    sentiment = Sentiment(
        put_call_ratio=raw.put_call_ratio,
        iv_rank=raw.iv_rank_approx,
        iv_rank_approx=raw.iv_rank_approx,
        iv_rank_is_approx=True,
        reddit_mention_spike_24h_pct=raw.reddit_mention_spike_24h_pct,
        reddit_positive_pct=raw.reddit_positive_pct,
        short_interest_pct=raw.short_interest_pct,
        institutional_net_shares_last_13f=raw.institutional_net_shares_last_13f,
        institutional_13f_as_of=raw.institutional_13f_as_of,
        institutional_13f_freshness=raw.institutional_13f_freshness,
        freshness=raw.freshness,
    )
    freshness = Freshness.DELAYED if raw.freshness != "missing" else Freshness.MISSING
    as_of = None
    if raw.institutional_13f_as_of is not None:
        try:
            as_of = datetime.fromisoformat(raw.institutional_13f_as_of).replace(tzinfo=timezone.utc)
        except ValueError:
            as_of = None
    return FreshValue(sentiment, freshness, as_of)


def fetch_macro() -> FreshValue[Macro]:
    raw = fetch_raw_macro()
    macro = Macro(
        days_to_next_fomc=raw.days_to_next_fomc,
        next_fomc_date=raw.next_fomc_date,
        rate_cut_probability_pct=raw.rate_cut_probability_pct,
        rate_cut_probability_source=raw.rate_cut_probability_source,
        treasury_10y=raw.treasury_10y,
        vix=raw.vix,
        freshness=raw.freshness,
    )
    freshness_map = {
        "live": Freshness.LIVE,
        "delayed": Freshness.DELAYED,
        "missing": Freshness.MISSING,
    }
    freshness = freshness_map.get(raw.freshness, Freshness.MISSING)
    as_of = None
    if raw.next_fomc_date is not None:
        try:
            as_of = datetime.fromisoformat(raw.next_fomc_date).replace(tzinfo=timezone.utc)
        except ValueError:
            as_of = None
    return FreshValue(macro, freshness, as_of)
