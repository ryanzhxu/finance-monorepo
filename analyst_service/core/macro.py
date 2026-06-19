from __future__ import annotations

import importlib
import json
import math
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup

from shared.models import Macro as SharedMacro

FED_FOMC_CALENDAR_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
FRED_DFEDTARU_URL = "https://api.stlouisfed.org/fred/series/observations?series_id=DFEDTARU&file_type=json&limit=1&sort_order=desc"
FALLBACK_2026_FOMC_DATES = ["2026-07-29", "2026-09-16", "2026-10-28", "2026-12-09"]
CACHE_PATH = Path(__file__).resolve().parents[1] / "cache" / "fomc_calendar.json"
CACHE_TTL = timedelta(hours=24)
SECURE_USER_AGENT = "finance-monorepo/0.1"
MONTH_PATTERN = (
    "January|February|March|April|May|June|July|August|September|October|November|December"
)
FOMC_DATE_PATTERN = re.compile(
    rf"(?P<start_month>{MONTH_PATTERN})\s+"
    rf"(?P<start_day>\d{{1,2}})"
    rf"(?:\s*-\s*(?:(?P<end_month>{MONTH_PATTERN})\s+)?(?P<end_day>\d{{1,2}}))?"
    rf",\s*(?P<year>20\d{{2}})",
    re.IGNORECASE,
)
MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}


@dataclass(frozen=True)
class MacroData:
    days_to_next_fomc: int | None = None
    next_fomc_date: str | None = None
    rate_cut_probability_pct: float | None = None
    rate_cut_probability_source: str = "missing"
    treasury_10y: float | None = None
    vix: float | None = None
    freshness: str = "missing"


def _today() -> date:
    return datetime.now(UTC).date()


def _load_yfinance() -> Any:
    return importlib.import_module("yfinance")


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


def _normalize_rate(value: float | None) -> float | None:
    if value is None:
        return None
    if value > 200:
        return round(value / 100.0, 4)
    if value > 20:
        return round(value / 10.0, 4)
    return round(value, 4)


def _read_calendar_cache(now: datetime) -> list[str] | None:
    if not CACHE_PATH.exists():
        return None
    try:
        payload = json.loads(CACHE_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    fetched_at_raw = payload.get("fetched_at")
    dates = payload.get("dates")
    if not isinstance(fetched_at_raw, str) or not isinstance(dates, list):
        return None
    try:
        fetched_at = datetime.fromisoformat(fetched_at_raw)
    except ValueError:
        return None
    if fetched_at.tzinfo is None:
        fetched_at = fetched_at.replace(tzinfo=UTC)
    else:
        fetched_at = fetched_at.astimezone(UTC)
    if now - fetched_at > CACHE_TTL:
        return None
    return [str(item) for item in dates if isinstance(item, str)]


def _write_calendar_cache(now: datetime, dates: list[str]) -> None:
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps({"fetched_at": now.isoformat(), "dates": dates}))
    except OSError:
        return None


def _extract_fomc_dates_from_html(html: str, today_value: date) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    candidate_texts = [
        " ".join(node.stripped_strings)
        for node in soup.find_all(["h3", "h4", "h5", "p", "li", "div", "span"])
    ]
    candidate_texts.append(soup.get_text(" ", strip=True))
    years = {today_value.year, today_value.year + 1}
    dates: set[str] = set()
    for text in candidate_texts:
        for match in FOMC_DATE_PATTERN.finditer(text):
            year = int(match.group("year"))
            if year not in years:
                continue
            end_month_name = (match.group("end_month") or match.group("start_month")).lower()
            end_day = int(match.group("end_day") or match.group("start_day"))
            end_month = MONTHS[end_month_name]
            try:
                meeting_end = date(year, end_month, end_day)
            except ValueError:
                continue
            dates.add(meeting_end.isoformat())
    return sorted(dates)


def _fetch_fomc_dates(today_value: date) -> list[str]:
    now = datetime.now(UTC)
    cached = _read_calendar_cache(now)
    if cached:
        return cached
    try:
        response = requests.get(
            FED_FOMC_CALENDAR_URL,
            headers={"User-Agent": SECURE_USER_AGENT},
            timeout=10.0,
        )
        response.raise_for_status()
        parsed_dates = _extract_fomc_dates_from_html(response.text, today_value)
        if parsed_dates:
            _write_calendar_cache(now, parsed_dates)
            return parsed_dates
    except Exception:
        pass

    try:
        if CACHE_PATH.exists():
            payload = json.loads(CACHE_PATH.read_text())
            stale_dates = payload.get("dates")
            if isinstance(stale_dates, list) and stale_dates:
                return [str(item) for item in stale_dates if isinstance(item, str)]
    except (json.JSONDecodeError, OSError):
        pass

    return FALLBACK_2026_FOMC_DATES


def _next_fomc(today_value: date) -> tuple[int | None, str | None]:
    future_dates = [
        candidate
        for candidate in _fetch_fomc_dates(today_value)
        if candidate >= today_value.isoformat()
    ]
    if not future_dates:
        future_dates = [candidate for candidate in FALLBACK_2026_FOMC_DATES if candidate >= today_value.isoformat()]
    if not future_dates:
        return None, None
    next_date = future_dates[0]
    next_date_obj = date.fromisoformat(next_date)
    return (next_date_obj - today_value).days, next_date


def _fast_info_last_price(ticker: Any) -> float | None:
    fast_info = getattr(ticker, "fast_info", None)
    if fast_info is None:
        return None
    if hasattr(fast_info, "last_price"):
        return _coerce_float(getattr(fast_info, "last_price"))
    if isinstance(fast_info, dict):
        return _coerce_float(fast_info.get("lastPrice") or fast_info.get("last_price"))
    if hasattr(fast_info, "get"):
        try:
            return _coerce_float(fast_info.get("lastPrice") or fast_info.get("last_price"))
        except Exception:
            return None
    return None


def _fetch_current_target_upper(yf: Any) -> float | None:
    try:
        irx_info = yf.Ticker("^IRX").info or {}
        for key in ("currentPrice", "regularMarketPrice", "previousClose"):
            rate = _normalize_rate(_coerce_float(irx_info.get(key)))
            if rate is not None:
                return rate
    except Exception:
        pass

    try:
        response = requests.get(
            FRED_DFEDTARU_URL,
            headers={"User-Agent": SECURE_USER_AGENT},
            timeout=10.0,
        )
        response.raise_for_status()
        payload = response.json()
        observations = payload.get("observations", [])
        for observation in reversed(observations):
            value = observation.get("value")
            if value in (None, "."):
                continue
            rate = _coerce_float(value)
            if rate is not None:
                return round(rate, 4)
    except Exception:
        return None
    return None


def _fetch_rate_cut_probability(yf: Any) -> tuple[float | None, str]:
    try:
        futures_price = _fast_info_last_price(yf.Ticker("ZQ=F"))
    except Exception:
        futures_price = None
    if futures_price is None:
        return None, "missing"
    implied_rate = 100.0 - futures_price
    current_target_upper = _fetch_current_target_upper(yf)
    if current_target_upper is None:
        return None, "missing"
    probability = max(0.0, min(100.0, ((current_target_upper - implied_rate) / 0.25) * 100.0))
    return round(probability, 2), "zq_futures_derived"


def _fetch_treasury_10y(yf: Any) -> float | None:
    try:
        value = _fast_info_last_price(yf.Ticker("^TNX"))
    except Exception:
        return None
    normalized = _normalize_rate(value)
    return None if normalized is None else round(normalized, 2)


def _fetch_vix(yf: Any) -> float | None:
    try:
        value = _fast_info_last_price(yf.Ticker("^VIX"))
    except Exception:
        return None
    return None if value is None else round(value, 2)


def fetch_macro() -> MacroData:
    today_value = _today()
    days_to_next_fomc, next_fomc_date = _next_fomc(today_value)

    try:
        yf = _load_yfinance()
    except Exception:
        yf = None

    rate_cut_probability_pct = None
    rate_cut_probability_source = "missing"
    treasury_10y = None
    vix = None
    if yf is not None:
        rate_cut_probability_pct, rate_cut_probability_source = _fetch_rate_cut_probability(yf)
        treasury_10y = _fetch_treasury_10y(yf)
        vix = _fetch_vix(yf)

    freshness = "missing"
    if rate_cut_probability_source == "zq_futures_derived" or treasury_10y is not None or vix is not None:
        freshness = "live"
    elif days_to_next_fomc is not None or next_fomc_date is not None:
        freshness = "delayed"

    return MacroData(
        days_to_next_fomc=days_to_next_fomc,
        next_fomc_date=next_fomc_date,
        rate_cut_probability_pct=rate_cut_probability_pct,
        rate_cut_probability_source=rate_cut_probability_source,
        treasury_10y=treasury_10y,
        vix=vix,
        freshness=freshness,
    )


def normalize_macro(macro: SharedMacro | None) -> SharedMacro:
    return macro or SharedMacro()
