from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, time, timezone

import httpx
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
from analyst_service.core.provider_clients.stockdata import (
    fetch_stockdata_eod,
    fetch_stockdata_quote,
    stockdata_api_key,
)
from analyst_service.core.provider_clients.finance_query import (
    fetch_finance_query_chart,
    fetch_finance_query_quote,
)
from analyst_service.core.regime import classify_regime
from analyst_service.core.sentiment import fetch_sentiment as fetch_raw_sentiment
from analyst_service.core.cache import get as cache_get, set as cache_set

logger = logging.getLogger(__name__)

ALPHA_VANTAGE_BASE_URL = "https://www.alphavantage.co/query"


def _empty_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])


def _estimated_ohlcv(current_price: float | None) -> pd.DataFrame:
    if current_price is None:
        return _empty_frame()
    end = pd.Timestamp.now(tz="UTC").tz_localize(None).normalize()
    index = pd.bdate_range(end=end, periods=260)
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


def _alpha_vantage_key() -> str | None:
    return os.getenv("ALPHA_VANTAGE_KEY") or os.getenv("ALPHA_VANTAGE_API_KEY")


def _coerce_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _is_alpha_vantage_quota_payload(payload: dict[str, object]) -> bool:
    for key in ("Information", "Note"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return True
    return False


def _normalize_ohlcv_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if isinstance(frame.columns, pd.MultiIndex):
        frame.columns = [column[0] for column in frame.columns]
    working = frame.rename(columns=str.lower).rename(columns={"adj close": "adj_close"})
    required = ["open", "high", "low", "close", "volume"]
    if any(column not in working.columns for column in required):
        return _empty_frame()
    cleaned = working[required].apply(pd.to_numeric, errors="coerce").dropna(how="all")
    if cleaned.empty:
        return _empty_frame()
    cleaned.index = pd.to_datetime(cleaned.index)
    return cleaned.sort_index()


def _fetch_alpha_vantage_ohlcv(symbol: str, key: str) -> pd.DataFrame:
    try:
        response = httpx.get(
            ALPHA_VANTAGE_BASE_URL,
            params={
                "function": "TIME_SERIES_DAILY",
                "symbol": symbol,
                "outputsize": "full",
                "apikey": key,
            },
            timeout=10.0,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        logger.warning("[%s] Alpha Vantage daily series fetch raised %s: %s", symbol, type(exc).__name__, exc)
        return _empty_frame()

    if not isinstance(payload, dict):
        return _empty_frame()
    if _is_alpha_vantage_quota_payload(payload):
        logger.warning("[%s] Alpha Vantage daily series quota exhausted", symbol)
        return _empty_frame()

    raw_series = payload.get("Time Series (Daily)")
    if not isinstance(raw_series, dict) or not raw_series:
        return _empty_frame()

    rows: list[dict[str, object]] = []
    for observed_at, values in raw_series.items():
        if not isinstance(values, dict):
            continue
        rows.append(
            {
                "date": observed_at,
                "open": _coerce_float(values.get("1. open")),
                "high": _coerce_float(values.get("2. high")),
                "low": _coerce_float(values.get("3. low")),
                "close": _coerce_float(values.get("4. close")),
                "volume": _coerce_float(values.get("5. volume")),
            }
        )

    if not rows:
        return _empty_frame()

    frame = pd.DataFrame.from_records(rows).set_index("date")
    normalized = _normalize_ohlcv_frame(frame)
    if normalized.empty:
        return normalized
    return normalized.tail(400)


def _fetch_alpha_vantage_quote(symbol: str, key: str) -> float | None:
    try:
        response = httpx.get(
            ALPHA_VANTAGE_BASE_URL,
            params={"function": "GLOBAL_QUOTE", "symbol": symbol, "apikey": key},
            timeout=10.0,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        logger.warning("[%s] Alpha Vantage quote fetch raised %s: %s", symbol, type(exc).__name__, exc)
        return None

    if not isinstance(payload, dict):
        return None
    if _is_alpha_vantage_quota_payload(payload):
        logger.warning("[%s] Alpha Vantage quote quota exhausted", symbol)
        return None

    quote = payload.get("Global Quote")
    if not isinstance(quote, dict):
        return None
    return _coerce_float(quote.get("05. price"))


def _fetch_yfinance_ohlcv(symbol: str) -> pd.DataFrame:
    try:
        import yfinance as yf

        frame = yf.download(symbol, period="18mo", interval="1d", progress=False, auto_adjust=False)
    except Exception as exc:
        logger.warning("[%s] yfinance download raised %s: %s", symbol, type(exc).__name__, exc)
        return _empty_frame()
    return _normalize_ohlcv_frame(frame)


def _fetch_spy_vs_ma200_pct() -> float | None:
    try:
        import yfinance as yf

        spy = yf.Ticker("SPY")
        spy_hist = spy.history(period="1y", interval="1d")
        normalized = _normalize_ohlcv_frame(spy_hist)
        if normalized.empty or "close" not in normalized:
            return None
        closes = normalized["close"].dropna()
        if closes.empty:
            return None
        spy_ma200 = closes.tail(200).mean()
        if pd.isna(spy_ma200) or not spy_ma200:
            return None
        spy_price = closes.iloc[-1]
        return round((float(spy_price) - float(spy_ma200)) / float(spy_ma200) * 100.0, 2)
    except Exception:
        return None


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
    return f"fundamentals:v3:{symbol.strip().upper()}"


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
    if any(
        value is None
        for value in (
            fundamentals.eps_surprise_pct,
            fundamentals.pe_percentile_5y,
            fundamentals.as_of,
        )
    ):
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
        return f"sentiment:v2:{symbol.strip().upper()}:{last_index}:{last_close}"
    return f"sentiment:v2:{symbol.strip().upper()}"


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
    if stockdata_api_key():
        try:
            stockdata_frame = fetch_stockdata_eod(symbol)
        except Exception as exc:
            logger.warning("[%s] StockData EOD fetch raised %s: %s", symbol, type(exc).__name__, exc)
            stockdata_frame = _empty_frame()
        if not stockdata_frame.empty:
            freshness, as_of = classify_price_freshness(stockdata_frame)
            return FreshValue(stockdata_frame, freshness, as_of)

    try:
        finance_query_frame = fetch_finance_query_chart(symbol, interval="1d", range_="2y")
    except Exception as exc:
        logger.warning("[%s] finance-query chart fetch raised %s: %s", symbol, type(exc).__name__, exc)
        finance_query_frame = _empty_frame()
    if not finance_query_frame.empty:
        freshness, as_of = classify_price_freshness(finance_query_frame)
        return FreshValue(finance_query_frame, freshness, as_of)

    av_key = _alpha_vantage_key()
    if av_key:
        av_frame = _fetch_alpha_vantage_ohlcv(symbol, av_key)
        if not av_frame.empty:
            freshness, as_of = classify_price_freshness(av_frame)
            return FreshValue(av_frame, freshness, as_of)

    yahoo_frame = _fetch_yfinance_ohlcv(symbol)
    if not yahoo_frame.empty:
        freshness, as_of = classify_price_freshness(yahoo_frame)
        return FreshValue(yahoo_frame, freshness, as_of)

    fallback_price = current_price
    if fallback_price is None and stockdata_api_key():
        try:
            fallback_price = fetch_stockdata_quote(symbol)
        except Exception as exc:
            logger.warning("[%s] StockData quote fetch raised %s: %s", symbol, type(exc).__name__, exc)
    if fallback_price is None:
        try:
            finance_query_quote = fetch_finance_query_quote(symbol)
        except Exception as exc:
            logger.warning("[%s] finance-query quote fetch raised %s: %s", symbol, type(exc).__name__, exc)
        else:
            fallback_price = _coerce_float(
                finance_query_quote.get("currentPrice")
                or finance_query_quote.get("regularMarketPrice")
                or finance_query_quote.get("previousClose")
            )
    if fallback_price is None and av_key:
        fallback_price = _fetch_alpha_vantage_quote(symbol, av_key)
    estimated = _estimated_ohlcv(fallback_price)
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
    spy_vs_ma200_pct = _fetch_spy_vs_ma200_pct()
    macro = Macro(
        days_to_next_fomc=raw.days_to_next_fomc,
        next_fomc_date=raw.next_fomc_date,
        rate_cut_probability_pct=raw.rate_cut_probability_pct,
        rate_cut_probability_source=raw.rate_cut_probability_source,
        treasury_10y=raw.treasury_10y,
        vix=raw.vix,
        freshness=raw.freshness,
        market_regime=classify_regime(
            raw.vix,
            raw.treasury_10y,
            spy_vs_ma200_pct,
            raw.days_to_next_fomc,
        ),
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
