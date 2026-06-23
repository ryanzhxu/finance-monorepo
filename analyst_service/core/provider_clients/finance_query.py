from __future__ import annotations

import os
from typing import Any

import httpx
import pandas as pd

FINANCE_QUERY_BASE_URL = "https://finance-query.com/v2"
_DEFAULT_TIMEOUT = 10.0


def finance_query_base_url() -> str:
    return (os.getenv("FINANCE_QUERY_BASE_URL") or FINANCE_QUERY_BASE_URL).rstrip("/")


def _request(path: str, params: dict[str, Any] | None = None, timeout: float = _DEFAULT_TIMEOUT) -> dict[str, Any]:
    response = httpx.get(
        f"{finance_query_base_url()}{path}",
        params=params or {},
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, dict) else {}


def fetch_finance_query_quote(symbol: str) -> dict[str, Any]:
    normalized_symbol = symbol.strip().upper()
    if not normalized_symbol:
        return {}
    return _request(f"/quote/{normalized_symbol}", {"logo": "true"})


def fetch_finance_query_chart(symbol: str, interval: str = "1d", range_: str = "2y") -> pd.DataFrame:
    normalized_symbol = symbol.strip().upper()
    if not normalized_symbol:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    payload = _request(
        f"/chart/{normalized_symbol}",
        {"interval": interval, "range": range_},
    )
    candles = payload.get("candles")
    if not isinstance(candles, list) or not candles:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    rows: list[dict[str, Any]] = []
    for candle in candles:
        if not isinstance(candle, dict):
            continue
        rows.append(
            {
                "date": candle.get("timestamp"),
                "open": candle.get("open"),
                "high": candle.get("high"),
                "low": candle.get("low"),
                "close": candle.get("close"),
                "volume": candle.get("volume"),
            }
        )

    if not rows:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    frame = pd.DataFrame.from_records(rows)
    expected = {"date", "open", "high", "low", "close", "volume"}
    if not expected.issubset(frame.columns):
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    frame["date"] = pd.to_datetime(frame["date"], unit="s", utc=True, errors="coerce")
    working = frame.dropna(subset=["date"]).drop_duplicates(subset=["date"]).set_index("date").sort_index()
    working.index = working.index.tz_convert(None)
    for column in ["open", "high", "low", "close", "volume"]:
        working[column] = pd.to_numeric(working[column], errors="coerce")
    return working.dropna(how="all")


def search_finance_query_symbols(query: str, limit: int = 6) -> list[dict[str, str]]:
    normalized_query = query.strip()
    if not normalized_query:
        return []

    payload = _request("/lookup", {"q": normalized_query})
    quotes = payload.get("quotes")
    if not isinstance(quotes, list):
        return []

    upper_query = normalized_query.upper()
    results: list[dict[str, str]] = []
    for quote in quotes:
        if not isinstance(quote, dict):
            continue
        symbol = str(quote.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        quote_type = str(quote.get("quoteType") or quote.get("type") or "").strip().upper()
        if quote_type and quote_type != "EQUITY":
            continue
        results.append(
            {
                "symbol": symbol,
                "name": str(
                    quote.get("longName")
                    or quote.get("shortName")
                    or quote.get("longname")
                    or quote.get("shortname")
                    or ""
                ).strip(),
                "exchange": str(quote.get("exchange") or "").strip(),
                "type": "EQUITY",
            }
        )

    results.sort(key=lambda item: (item["symbol"] != upper_query, not item["symbol"].startswith(upper_query), item["symbol"]))
    return results[:limit]
