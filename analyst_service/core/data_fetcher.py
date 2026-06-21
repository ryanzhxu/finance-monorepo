from __future__ import annotations

import json
import os
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
from analyst_service.core.cache import get as cache_get, set as cache_set


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


def _cache_ttl(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _deserialize_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def _load_cached_payload(key: str) -> dict[str, object] | None:
    cached = cache_get(key)
    if cached is None:
        return None
    try:
        payload = json.loads(cached)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _store_cached_payload(key: str, payload: dict[str, object], ttl: int) -> None:
    cache_set(key, json.dumps(payload), ttl)


def _fundamentals_cache_key(symbol: str) -> str:
    return f"fundamentals:v1:{symbol.strip().upper()}"


def _is_sparse_fundamentals_payload(fundamentals: Fundamentals, freshness: Freshness) -> bool:
    core_values = (
        fundamentals.company_name,
        fundamentals.eps_surprise_pct,
        fundamentals.pe_ratio,
        fundamentals.pb_ratio,
        fundamentals.ps_ratio,
        fundamentals.ev_ebitda,
        fundamentals.pe_percentile_5y,
        fundamentals.analyst_upgrades_30d,
        fundamentals.analyst_downgrades_30d,
        fundamentals.revenue_growth_yoy_pct,
        fundamentals.fcf_trend,
        fundamentals.gross_margin_pct,
        fundamentals.as_of,
    )
    return freshness == Freshness.MISSING and all(value is None for value in core_values)


def _fundamentals_cache_ttl(fundamentals: Fundamentals, freshness: Freshness) -> int:
    if _is_sparse_fundamentals_payload(fundamentals, freshness):
        return _cache_ttl("FUNDAMENTAL_SPARSE_CACHE_TTL", 300)
    return _cache_ttl("FUNDAMENTAL_CACHE_TTL", 86400)


def _sentiment_cache_key(symbol: str, price_history: pd.DataFrame | None) -> str:
    if isinstance(price_history, pd.DataFrame) and not price_history.empty:
        last_index = price_history.index[-1]
        last_close = None
        for column in price_history.columns:
            if str(column).lower() == "close":
                series = price_history[column].dropna()
                if not series.empty:
                    last_close = float(series.iloc[-1])
                break
        return f"sentiment:v1:{symbol.strip().upper()}:{last_index}:{last_close}"
    return f"sentiment:v1:{symbol.strip().upper()}"


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
    cached_payload = _load_cached_payload(_fundamentals_cache_key(symbol))
    if cached_payload is not None:
        cached_value = cached_payload.get("value")
        cached_freshness = cached_payload.get("freshness")
        if isinstance(cached_value, dict) and isinstance(cached_freshness, str):
            try:
                return FreshValue(
                    Fundamentals(**cached_value),
                    Freshness(cached_freshness),
                    _deserialize_datetime(cached_payload.get("as_of")),
                )
            except ValueError:
                pass

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
        company_name=raw.company_name,
    )
    freshness = Freshness.QUARTERLY if raw.freshness == "quarterly" else Freshness.MISSING
    as_of = None
    if raw.as_of is not None:
        try:
            as_of = datetime.fromisoformat(raw.as_of).replace(tzinfo=timezone.utc)
        except ValueError:
            as_of = None
    result = FreshValue(fundamentals, freshness, as_of)
    _store_cached_payload(
        _fundamentals_cache_key(symbol),
        {
            "value": fundamentals.model_dump(mode="json"),
            "freshness": freshness.value,
            "as_of": as_of.isoformat() if as_of is not None else None,
        },
        _fundamentals_cache_ttl(fundamentals, freshness),
    )
    return result


def fetch_sentiment(symbol: str, price_history: pd.DataFrame | None = None) -> FreshValue[Sentiment]:
    cache_key = _sentiment_cache_key(symbol, price_history)
    cached_payload = _load_cached_payload(cache_key)
    if cached_payload is not None:
        cached_value = cached_payload.get("value")
        cached_freshness = cached_payload.get("freshness")
        if isinstance(cached_value, dict) and isinstance(cached_freshness, str):
            try:
                return FreshValue(
                    Sentiment(**cached_value),
                    Freshness(cached_freshness),
                    _deserialize_datetime(cached_payload.get("as_of")),
                )
            except ValueError:
                pass

    raw = fetch_raw_sentiment(symbol, price_history=price_history)
    sentiment = Sentiment(
        put_call_ratio=raw.put_call_ratio,
        iv_rank=raw.iv_rank_approx,
        iv_rank_approx=raw.iv_rank_approx,
        iv_rank_is_approx=True,
        news_sentiment_score=raw.news_sentiment_score,
        news_headline_count=raw.news_headline_count,
        news_sentiment_source=raw.news_sentiment_source,
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
    result = FreshValue(sentiment, freshness, as_of)
    _store_cached_payload(
        cache_key,
        {
            "value": sentiment.model_dump(mode="json"),
            "freshness": freshness.value,
            "as_of": as_of.isoformat() if as_of is not None else None,
        },
        _cache_ttl("SENTIMENT_CACHE_TTL", 900),
    )
    return result


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
