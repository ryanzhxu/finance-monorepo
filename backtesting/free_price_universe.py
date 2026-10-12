from __future__ import annotations

import csv
from io import StringIO
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

import httpx

from shared.config_loader import load_yaml_config

FREE_PRICE_UNIVERSE_CONFIG_PATH = Path(__file__).resolve().parent / "config" / "free_price_universe.yaml"


@lru_cache
def load_free_price_universe_config() -> dict[str, Any]:
    return load_yaml_config(FREE_PRICE_UNIVERSE_CONFIG_PATH, {"nasdaq_trader", "download"})


def fetch_current_us_common_symbols(
    *,
    get: Callable[[str], str] | None = None,
) -> list[str]:
    """Resolve current US common-stock listings from Nasdaq Trader directories.

    This is intentionally a current-listings universe. It must not be treated as
    a survivorship-bias-free historical membership source.
    """

    config = load_free_price_universe_config()["nasdaq_trader"]
    if get is None:
        get = _download_text
    nasdaq_rows = _parse_rows(get(str(config["listed_url"])))
    other_rows = _parse_rows(get(str(config["other_listed_url"])))
    symbols = {
        symbol
        for row in nasdaq_rows
        if _is_eligible(row, config, other_exchange=False)
        for symbol in [_yahoo_symbol(_value(row, "Symbol"))]
        if symbol
    }
    symbols.update(
        symbol
        for row in other_rows
        if _is_eligible(row, config, other_exchange=True)
        for symbol in [_yahoo_symbol(_value(row, "NASDAQ Symbol", "ACT Symbol", "Symbol"))]
        if symbol
    )
    return sorted(symbols)


def _download_text(url: str) -> str:
    response = httpx.get(url, timeout=30.0, follow_redirects=True)
    response.raise_for_status()
    return response.text


def _parse_rows(content: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for row in csv.DictReader(StringIO(content), delimiter="|"):
        if any(str(value or "").startswith("File Creation Time") for value in row.values()):
            continue
        rows.append({str(key).strip(): str(value or "").strip() for key, value in row.items() if key is not None})
    return rows


def _is_eligible(row: dict[str, str], config: dict[str, Any], *, other_exchange: bool) -> bool:
    if _value(row, "Test Issue").upper() != "N":
        return False
    if _value(row, "ETF").upper() == "Y":
        return False
    financial_status = _value(row, "Financial Status").upper()
    if financial_status not in {"", "N"}:
        return False
    if other_exchange and _value(row, "Exchange").upper() not in set(config["eligible_exchange_codes"]):
        return False
    security_name = _value(row, "Security Name").lower()
    if not any(term in security_name for term in config["required_security_name_terms"]):
        return False
    return not any(term in security_name for term in config["excluded_security_name_terms"])


def _value(row: dict[str, str], *names: str) -> str:
    for name in names:
        if value := row.get(name):
            return value.strip()
    return ""


def _yahoo_symbol(symbol: str) -> str:
    normalized = symbol.strip().upper().replace(".", "-")
    return normalized if normalized.replace("-", "").isalnum() else ""
