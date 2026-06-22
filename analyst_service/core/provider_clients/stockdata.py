from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pandas as pd

STOCKDATA_BASE_URL = "https://api.stockdata.org/v1"
_DEFAULT_TIMEOUT = 10.0


def stockdata_api_key() -> str | None:
    return os.getenv("STOCKDATA_API_KEY")


def _request(path: str, params: dict[str, Any], timeout: float = _DEFAULT_TIMEOUT) -> dict[str, Any]:
    api_key = stockdata_api_key()
    if not api_key:
        return {}
    response = httpx.get(
        f"{STOCKDATA_BASE_URL}{path}",
        params={**params, "api_token": api_key},
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, dict) else {}


def fetch_stockdata_quote(symbol: str) -> float | None:
    payload = _request("/data/quote", {"symbols": symbol.strip().upper()})
    rows = payload.get("data")
    if not isinstance(rows, list) or not rows:
        return None
    first = rows[0]
    if not isinstance(first, dict):
        return None
    price = first.get("price")
    try:
        return float(price) if price is not None else None
    except (TypeError, ValueError):
        return None


def fetch_stockdata_eod(symbol: str, total_days: int = 540, chunk_days: int = 180) -> pd.DataFrame:
    api_key = stockdata_api_key()
    if not api_key:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    normalized_symbol = symbol.strip().upper()
    end_date = datetime.now(UTC).date()
    start_date = end_date - timedelta(days=total_days - 1)
    windows: list[tuple[datetime.date, datetime.date]] = []
    cursor = start_date
    while cursor <= end_date:
        window_end = min(cursor + timedelta(days=chunk_days - 1), end_date)
        windows.append((cursor, window_end))
        cursor = window_end + timedelta(days=1)

    rows: list[dict[str, Any]] = []
    for window_start, window_end in windows:
        payload = _request(
            "/data/eod",
            {
                "symbols": normalized_symbol,
                "date_from": window_start.isoformat(),
                "date_to": window_end.isoformat(),
                "sort": "asc",
            },
        )
        data = payload.get("data")
        if not isinstance(data, list):
            continue
        for item in data:
            if not isinstance(item, dict):
                continue
            rows.append(item)

    if not rows:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    frame = pd.DataFrame.from_records(rows)
    expected = {"date", "open", "high", "low", "close", "volume"}
    if not expected.issubset(frame.columns):
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    working = frame.loc[:, ["date", "open", "high", "low", "close", "volume"]].copy()
    working["date"] = pd.to_datetime(working["date"], errors="coerce")
    working = working.dropna(subset=["date"]).drop_duplicates(subset=["date"]).set_index("date").sort_index()
    for column in ["open", "high", "low", "close", "volume"]:
        working[column] = pd.to_numeric(working[column], errors="coerce")
    cleaned = working.dropna(how="all")
    return cleaned.tail(400)


def search_stockdata_symbols(query: str, limit: int = 6) -> list[dict[str, str]]:
    payload = _request("/entity/search", {"search": query.strip()})
    rows = payload.get("data")
    if not isinstance(rows, list):
        return []

    normalized_query = query.strip().upper()
    results: list[dict[str, str]] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol") or "").strip().upper()
        name = str(item.get("name") or "").strip()
        item_type = str(item.get("type") or "").strip().upper()
        exchange = str(item.get("exchange") or item.get("mic_code") or "").strip()
        if not symbol or item_type != "EQUITY":
            continue
        results.append(
            {
                "symbol": symbol,
                "name": name,
                "exchange": exchange,
                "type": "EQUITY",
            }
        )

    results.sort(key=lambda item: (item["symbol"] != normalized_query, not item["symbol"].startswith(normalized_query), item["symbol"]))
    return results[:limit]
