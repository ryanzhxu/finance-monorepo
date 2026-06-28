from __future__ import annotations

import importlib
import io
import logging
import math
import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pandas as pd

from shared.models import Sentiment as SharedSentiment
from analyst_service.core.settings import load_service_config
from analyst_service.core.provider_clients.finance_query import fetch_finance_query_quote

SEC_USER_AGENT = "finance-monorepo/0.1 contact=local"
MARKETAUX_BASE = "https://api.marketaux.com/v1/news/all"
_KNOWN_CIKS = {
    "AAPL": "0000320193",
    "AMZN": "0001018724",
    "GOOGL": "0001652044",
    "META": "0001326801",
    "MSFT": "0000789019",
    "NVDA": "0001045810",
    "TSLA": "0001318605",
}
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SentimentData:
    put_call_ratio: float | None = None
    iv_rank_approx: float | None = None
    short_interest_pct: float | None = None
    institutional_net_shares_last_13f: int | None = None
    institutional_13f_as_of: str | None = None
    institutional_13f_freshness: str = "delayed_45d"
    news_sentiment_score: float | None = None
    news_headline_count: int | None = None
    news_sentiment_source: str | None = None
    reddit_mention_spike_24h_pct: float | None = None
    reddit_positive_pct: float | None = None
    freshness: str = "missing"


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric):
        return None
    return numeric


def _load_yfinance() -> Any:
    return importlib.import_module("yfinance")


def _alpha_vantage_key() -> str | None:
    return os.getenv("ALPHA_VANTAGE_KEY") or os.getenv("ALPHA_VANTAGE_API_KEY")


def _news_sentiment_config() -> dict[str, Any]:
    thresholds = load_service_config()["thresholds"]
    return dict(thresholds.get("news_sentiment", {}))


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _normalize_column_name(value: Any) -> str:
    return "".join(character.lower() for character in str(value) if character.isalnum())


def _extract_close_series(price_history: pd.DataFrame | None) -> pd.Series | None:
    if not isinstance(price_history, pd.DataFrame) or price_history.empty:
        return None
    close_column = next(
        (column for column in price_history.columns if _normalize_column_name(column) == "close"),
        None,
    )
    if close_column is None:
        return None
    series = price_history[close_column].dropna()
    if series.empty:
        return None
    return series.astype(float)


def _percentile_rank(current_value: float, values: pd.Series) -> float | None:
    if values.empty:
        return None
    less_than = int((values < current_value).sum())
    equal_to = int((values == current_value).sum())
    percentile = ((less_than + (0.5 * equal_to)) / len(values)) * 100.0
    return round(max(0.0, min(100.0, percentile)), 2)


def _compute_hv_rank(price_history: pd.DataFrame | None) -> float | None:
    close_series = _extract_close_series(price_history)
    if close_series is None or len(close_series) < 40:
        return None
    returns = close_series.pct_change().dropna()
    if len(returns) < 20:
        return None
    hv_series = returns.rolling(20).std().dropna() * math.sqrt(252.0)
    if hv_series.empty:
        return None
    window = hv_series.tail(252)
    current_hv = _coerce_float(window.iloc[-1])
    if current_hv is None:
        return None
    return _percentile_rank(current_hv, window)


def _compute_put_call_ratio(ticker: Any) -> float | None:
    expiries = getattr(ticker, "options", ())
    if not expiries:
        return None
    nearest_expiry = expiries[0]
    option_chain = ticker.option_chain(nearest_expiry)
    calls = getattr(option_chain, "calls", None)
    puts = getattr(option_chain, "puts", None)
    if not isinstance(calls, pd.DataFrame) or not isinstance(puts, pd.DataFrame):
        return None
    if "volume" not in calls.columns or "volume" not in puts.columns:
        return None
    call_volume = _coerce_float(calls["volume"].fillna(0).sum())
    put_volume = _coerce_float(puts["volume"].fillna(0).sum())
    if call_volume is None or put_volume is None or call_volume <= 0:
        return None
    return round(put_volume / call_volume, 4)


def _fetch_alpha_vantage_put_call_ratio(symbol: str, key: str) -> float | None:
    response = httpx.get(
        "https://www.alphavantage.co/query",
        params={
            "function": "HISTORICAL_PUT_CALL_RATIO",
            "symbol": symbol,
            "apikey": key,
        },
        timeout=10.0,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        return None
    return _coerce_float(payload.get("put_call_ratio_full_chain"))


def _extract_cik(symbol: str, info: dict[str, Any]) -> str | None:
    for key in ("cik", "CIK", "secCik"):
        value = info.get(key)
        if value is None:
            continue
        digits = "".join(character for character in str(value) if character.isdigit())
        if digits:
            return digits.zfill(10)
    return _KNOWN_CIKS.get(symbol.upper())


def _sec_get(url: str, **kwargs: Any) -> httpx.Response:
    headers = dict(kwargs.pop("headers", {}) or {})
    headers.setdefault("User-Agent", SEC_USER_AGENT)
    headers.setdefault("Accept", "*/*")
    return httpx.get(url, headers=headers, timeout=15.0, **kwargs)


def _lookup_cik_via_sec_search(symbol: str) -> str | None:
    response = _sec_get(
        "https://efts.sec.gov/LATEST/search-index",
        params={
            "q": f"\"{symbol}\"",
            "dateRange": "custom",
            "startdt": "2020-01-01",
            "enddt": "2026-01-01",
            "forms": "10-K",
        },
        headers={"Accept": "application/json"},
    )
    response.raise_for_status()
    payload = response.json()
    hits = payload.get("hits", {}).get("hits", [])
    for hit in hits:
        cik = (
            hit.get("_source", {}).get("ciks", [None])[0]
            or hit.get("_source", {}).get("cik")
            or hit.get("_id")
        )
        if cik is None:
            continue
        digits = "".join(character for character in str(cik) if character.isdigit())
        if digits:
            return digits.zfill(10)
    return None


def _get_latest_13f_filing(cik: str) -> tuple[str | None, str | None]:
    response = _sec_get(
        f"https://data.sec.gov/submissions/CIK{cik}.json",
        headers={"Accept": "application/json"},
    )
    response.raise_for_status()
    payload = response.json()
    recent = payload.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    accession_numbers = recent.get("accessionNumber", [])
    filing_dates = recent.get("filingDate", [])
    primary_documents = recent.get("primaryDocument", [])
    for form, accession_number, filing_date, primary_document in zip(forms, accession_numbers, filing_dates, primary_documents):
        if str(form).upper().startswith("13F-HR"):
            accession = str(accession_number)
            accession_no_dashes = accession.replace("-", "")
            _ = primary_document
            filing_date_value = str(filing_date or "")[:10] or None
            return accession_no_dashes, filing_date_value
    return None, None


def _choose_holdings_document(cik: str, accession_no_dashes: str) -> str | None:
    base_url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession_no_dashes}"
    response = _sec_get(f"{base_url}/index.json", headers={"Accept": "application/json"})
    response.raise_for_status()
    payload = response.json()
    items = payload.get("directory", {}).get("item", [])
    preferred: list[str] = []
    fallback: list[str] = []
    for item in items:
        name = str(item.get("name", ""))
        lower_name = name.lower()
        if "infotable" in lower_name:
            preferred.append(name)
        elif lower_name.endswith((".xml", ".htm", ".html", ".txt")):
            fallback.append(name)
    chosen = (preferred or fallback or [None])[0]
    return None if chosen is None else f"{base_url}/{chosen}"


def _xml_local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _parse_13f_holdings_xml(document_text: str) -> int | None:
    root = ET.fromstring(document_text)
    total_shares = 0
    found = False
    for info_table in root.iter():
        if _xml_local_name(info_table.tag) != "infoTable":
            continue
        share_type = None
        share_amount = None
        for node in info_table.iter():
            local_name = _xml_local_name(node.tag)
            if local_name == "sshPrnamtType":
                share_type = (node.text or "").strip().upper()
            elif local_name == "sshPrnamt":
                share_amount = _coerce_float((node.text or "").replace(",", ""))
        if share_type == "SH" and share_amount is not None:
            total_shares += int(share_amount)
            found = True
    return total_shares if found else None


def _parse_13f_holdings_html(document_text: str) -> int | None:
    tables = pd.read_html(io.StringIO(document_text))
    for table in tables:
        normalized_columns = {_normalize_column_name(column): column for column in table.columns}
        share_type_column = normalized_columns.get("shprn") or normalized_columns.get("sshprnamttype")
        share_amount_column = normalized_columns.get("sharesprnamt") or normalized_columns.get("sshprnamt")
        if share_type_column is None or share_amount_column is None:
            continue
        share_rows = table.loc[
            table[share_type_column].astype(str).str.upper().str.strip() == "SH",
            share_amount_column,
        ]
        numeric = pd.to_numeric(share_rows.astype(str).str.replace(",", "", regex=False), errors="coerce").dropna()
        if not numeric.empty:
            return int(numeric.sum())
    return None


def _fetch_institutional_13f_total(symbol: str, info: dict[str, Any]) -> tuple[int | None, str | None]:
    cik = _extract_cik(symbol, info)
    if cik is None:
        try:
            cik = _lookup_cik_via_sec_search(symbol)
        except Exception:
            cik = None
    if cik is None:
        return None, None
    accession_no_dashes, filing_date = _get_latest_13f_filing(cik)
    if accession_no_dashes is None:
        return None, filing_date
    document_url = _choose_holdings_document(cik, accession_no_dashes)
    if document_url is None:
        return None, filing_date
    response = _sec_get(document_url)
    response.raise_for_status()
    document_text = response.text
    try:
        total = _parse_13f_holdings_xml(document_text)
    except ET.ParseError:
        total = _parse_13f_holdings_html(document_text)
    return total, filing_date


def _estimate_institutional_13f_total(info: dict[str, Any], finance_query_quote: dict[str, Any]) -> int | None:
    shares_outstanding = _coerce_float(
        info.get("sharesOutstanding")
        or finance_query_quote.get("sharesOutstanding")
        or finance_query_quote.get("shares_outstanding")
    )
    if shares_outstanding is None or shares_outstanding <= 0:
        return None

    held_percent = _coerce_float(
        info.get("heldPercentInstitutions")
        or finance_query_quote.get("heldPercentInstitutions")
        or finance_query_quote.get("held_percent_institutions")
    )
    if held_percent is None or held_percent <= 0:
        return None

    if held_percent > 1:
        held_percent /= 100.0

    estimated_total = int(round(shares_outstanding * held_percent))
    return estimated_total if estimated_total > 0 else None


def _reddit_sentiment_score(text: str) -> float:
    bullish_terms = ("buy", "bull", "bullish", "long", "beat", "upgrade", "strong")
    bearish_terms = ("sell", "bear", "bearish", "short", "miss", "downgrade", "weak")
    normalized = text.lower()
    bullish = sum(term in normalized for term in bullish_terms)
    bearish = sum(term in normalized for term in bearish_terms)
    return float(bullish - bearish)


def _fetch_reddit_sentiment(symbol: str) -> tuple[float | None, float | None]:
    client_id = os.getenv("REDDIT_CLIENT_ID")
    client_secret = os.getenv("REDDIT_CLIENT_SECRET")
    if not client_id or not client_secret:
        return None, None

    token_response = httpx.post(
        "https://www.reddit.com/api/v1/access_token",
        auth=(client_id, client_secret),
        data={"grant_type": "client_credentials"},
        headers={"User-Agent": "finance-monorepo/0.1"},
        timeout=10.0,
    )
    token_response.raise_for_status()
    access_token = token_response.json().get("access_token")
    if not access_token:
        return None, None

    headers = {
        "Authorization": f"Bearer {access_token}",
        "User-Agent": "finance-monorepo/0.1",
    }
    search_url = "https://oauth.reddit.com/search"
    today_response = httpx.get(
        search_url,
        params={"q": symbol, "sort": "new", "t": "day", "limit": 50, "restrict_sr": False},
        headers=headers,
        timeout=10.0,
    )
    week_response = httpx.get(
        search_url,
        params={"q": symbol, "sort": "new", "t": "week", "limit": 100, "restrict_sr": False},
        headers=headers,
        timeout=10.0,
    )
    today_response.raise_for_status()
    week_response.raise_for_status()

    today_posts = today_response.json().get("data", {}).get("children", [])
    week_posts = week_response.json().get("data", {}).get("children", [])
    if not today_posts:
        return 0.0, None

    baseline = max((len(week_posts) - len(today_posts)) / 6.0, 1.0)
    mention_spike = round(((len(today_posts) / baseline) - 1.0) * 100.0, 2)

    positive = 0
    scored_posts = 0
    for child in today_posts:
        data = child.get("data", {})
        text = f"{data.get('title', '')} {data.get('selftext', '')}".strip()
        if not text:
            continue
        scored_posts += 1
        if _reddit_sentiment_score(text) >= 0:
            positive += 1
    positive_pct = None if scored_posts == 0 else round((positive / scored_posts) * 100.0, 2)
    return mention_spike, positive_pct


def score_headlines(titles: list[str]) -> float | None:
    config = _news_sentiment_config()
    min_headlines = int(config.get("min_headlines_for_signal", 3))
    usable_titles = [title.strip() for title in titles if title and title.strip()]
    if len(usable_titles) < min_headlines:
        return None

    bullish_words = {str(word).lower() for word in config.get("bullish_words", [])}
    bearish_words = {str(word).lower() for word in config.get("bearish_words", [])}
    bullish_hits = 0
    bearish_hits = 0

    for title in usable_titles:
        tokens = re.findall(r"[a-z0-9]+", title.lower())
        bullish_hits += sum(token in bullish_words for token in tokens)
        bearish_hits += sum(token in bearish_words for token in tokens)

    score = (bullish_hits - bearish_hits) / len(usable_titles)
    return round(max(-1.0, min(1.0, score)), 4)


def fetch_marketaux_headlines(symbol: str) -> list[str]:
    key = os.getenv("MARKETAUX_API_KEY")
    if not key:
        logger.warning("MARKETAUX_API_KEY not set — news sentiment unavailable")
        return []
    try:
        response = httpx.get(
            MARKETAUX_BASE,
            params={
                "symbols": symbol,
                "filter_entities": "true",
                "language": "en",
                "api_token": key,
            },
            timeout=8.0,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            return []
        articles = payload.get("data", [])
        if not isinstance(articles, list):
            return []
        headlines: list[str] = []
        for article in articles:
            if not isinstance(article, dict):
                continue
            title = str(article.get("title") or "").strip()
            if not title:
                continue
            description = str(article.get("description") or "").strip()
            combined = " ".join(part for part in (title, description) if part).strip()
            if combined:
                headlines.append(combined)
        return headlines
    except Exception as exc:
        logger.warning("Marketaux news fetch failed for %s: %s", symbol, exc)
        return []


def fetch_sentiment(symbol: str, price_history: pd.DataFrame | None = None) -> SentimentData:
    info: dict[str, Any] = {}
    put_call_ratio = None
    short_interest_pct = None
    av_key = _alpha_vantage_key()
    try:
        finance_query_quote = fetch_finance_query_quote(symbol)
    except Exception:
        finance_query_quote = {}

    try:
        yf = _load_yfinance()
        ticker = yf.Ticker(symbol)
        try:
            info = ticker.info or {}
        except Exception:
            info = {}
        try:
            put_call_ratio = _compute_put_call_ratio(ticker)
        except Exception:
            put_call_ratio = None
        short_interest_raw = _coerce_float(
            info.get("shortPercentOfFloat")
            or finance_query_quote.get("shortPercentOfFloat")
        )
        short_interest_pct = None if short_interest_raw is None else round(short_interest_raw * 100.0, 2)
    except Exception:
        ticker = None
        short_interest_raw = _coerce_float(finance_query_quote.get("shortPercentOfFloat"))
        short_interest_pct = None if short_interest_raw is None else round(short_interest_raw * 100.0, 2)

    if put_call_ratio is None and av_key:
        try:
            put_call_ratio = _fetch_alpha_vantage_put_call_ratio(symbol, av_key)
        except Exception:
            put_call_ratio = None

    iv_rank_approx = _compute_hv_rank(price_history)

    try:
        institutional_total, filing_date = _fetch_institutional_13f_total(symbol, info)
    except Exception:
        institutional_total, filing_date = None, None
    institutional_13f_freshness = "delayed_45d"
    if institutional_total is None:
        institutional_total = _estimate_institutional_13f_total(info, finance_query_quote)
        if institutional_total is not None:
            institutional_13f_freshness = "estimated"

    try:
        reddit_mention_spike_24h_pct, reddit_positive_pct = _fetch_reddit_sentiment(symbol)
    except Exception:
        reddit_mention_spike_24h_pct, reddit_positive_pct = None, None

    news_source = None
    headlines = fetch_marketaux_headlines(symbol)
    if headlines:
        news_source = "marketaux"
    news_headline_count = len(headlines) if headlines else None
    news_sentiment_score = score_headlines(headlines) if headlines else None

    freshness = "missing"
    if any(
        value is not None
        for value in (
            put_call_ratio,
            iv_rank_approx,
            short_interest_pct,
            institutional_total,
            filing_date,
            news_sentiment_score,
            news_headline_count,
            reddit_mention_spike_24h_pct,
            reddit_positive_pct,
        )
    ):
        freshness = "delayed"

    return SentimentData(
        put_call_ratio=put_call_ratio,
        iv_rank_approx=iv_rank_approx,
        short_interest_pct=short_interest_pct,
        institutional_net_shares_last_13f=institutional_total,
        institutional_13f_as_of=filing_date,
        institutional_13f_freshness=institutional_13f_freshness,
        news_sentiment_score=news_sentiment_score,
        news_headline_count=news_headline_count,
        news_sentiment_source=news_source,
        reddit_mention_spike_24h_pct=reddit_mention_spike_24h_pct,
        reddit_positive_pct=reddit_positive_pct,
        freshness=freshness,
    )


def normalize_sentiment(sentiment: SharedSentiment | None) -> SharedSentiment:
    return sentiment or SharedSentiment()
