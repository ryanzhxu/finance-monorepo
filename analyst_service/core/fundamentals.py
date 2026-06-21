from __future__ import annotations

import importlib
import logging
import math
import os
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

import httpx
import pandas as pd

from shared.models import Fundamentals as SharedFundamentals

SEC_USER_AGENT = "finance-monorepo/0.1 contact=local"
ALPHA_VANTAGE_BASE_URL = "https://www.alphavantage.co/query"
YAHOO_SEARCH_URL = "https://query1.finance.yahoo.com/v1/finance/search"
_OPERATING_CASHFLOW_KEYS = (
    "Operating Cash Flow",
    "OperatingCashFlow",
    "Net Cash Provided By Operating Activities",
    "NetCashProvidedByUsedInOperatingActivities",
    "Net Cash From Operating Activities",
)
_CAPEX_KEYS = (
    "Capital Expenditure",
    "Capital Expenditures",
    "CapitalExpenditures",
    "Payments To Acquire Property Plant And Equipment",
    "PaymentsToAcquirePropertyPlantAndEquipment",
    "Property Plant Equipment Additions",
    "PropertyPlantAndEquipmentAdditions",
)
_REVENUE_KEYS = (
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "SalesRevenueNet",
    "Revenues",
)
_GROSS_PROFIT_KEYS = ("GrossProfit",)
_EPS_KEYS = (
    "EarningsPerShareDiluted",
    "EarningsPerShareBasicAndDiluted",
    "IncomeLossFromContinuingOperationsPerDilutedShare",
)
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FundamentalsData:
    eps_surprise_pct: float | None = None
    pe_ratio: float | None = None
    pb_ratio: float | None = None
    ps_ratio: float | None = None
    ev_ebitda: float | None = None
    pe_percentile_5y: float | None = None
    revenue_growth_yoy_pct: float | None = None
    fcf_trend: str | None = None
    gross_margin_pct: float | None = None
    analyst_upgrades_30d: int | None = None
    analyst_downgrades_30d: int | None = None
    freshness: Literal["quarterly", "missing"] = "missing"
    as_of: str | None = None
    company_name: str | None = None


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _load_yfinance() -> Any:
    return importlib.import_module("yfinance")


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(result):
        return None
    return result


def _maybe_percent(value: Any) -> float | None:
    numeric = _coerce_float(value)
    if numeric is None:
        return None
    if -1.5 <= numeric <= 1.5:
        numeric *= 100.0
    return round(numeric, 2)


def _normalize_label(value: Any) -> str:
    return "".join(character.lower() for character in str(value) if character.isalnum())


def _safe_frame(value: Any) -> pd.DataFrame | None:
    if isinstance(value, pd.DataFrame):
        return value.copy()
    return None


def _safe_timestamp(value: Any) -> pd.Timestamp | None:
    if value is None:
        return None
    try:
        timestamp = pd.Timestamp(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(timestamp):
        return None
    return timestamp.tz_localize(None) if timestamp.tzinfo is not None else timestamp


def _iso_date(value: Any) -> str | None:
    timestamp = _safe_timestamp(value)
    if timestamp is not None:
        return timestamp.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10]).isoformat()
        except ValueError:
            return None
    return None


def _latest_earnings_row(earnings_history: pd.DataFrame | None) -> tuple[pd.Series | None, str | None]:
    frame = _safe_frame(earnings_history)
    if frame is None or frame.empty:
        return None, None
    try:
        frame.index = pd.to_datetime(frame.index)
    except Exception:
        return None, None
    frame = frame.sort_index()
    latest_index = frame.index[-1]
    return frame.iloc[-1], latest_index.date().isoformat()


def _extract_latest_surprise(earnings_history: pd.DataFrame | None) -> tuple[float | None, str | None]:
    latest_row, as_of = _latest_earnings_row(earnings_history)
    if latest_row is None:
        return None, as_of
    return _maybe_percent(latest_row.get("surprisePercent")), as_of


def _extract_current_price(info: dict[str, Any], price_history: pd.DataFrame | None) -> float | None:
    for key in ("currentPrice", "regularMarketPrice", "previousClose"):
        value = _coerce_float(info.get(key))
        if value is not None and value > 0:
            return value
    frame = _safe_frame(price_history)
    if frame is None or frame.empty:
        return None
    close_column = next((column for column in frame.columns if str(column).lower() == "close"), None)
    if close_column is None:
        return None
    return _coerce_float(frame[close_column].dropna().iloc[-1]) if not frame[close_column].dropna().empty else None


def _close_on_or_before(price_history: pd.DataFrame | None, when: Any) -> float | None:
    frame = _safe_frame(price_history)
    timestamp = _safe_timestamp(when)
    if frame is None or frame.empty or timestamp is None:
        return None
    close_column = next((column for column in frame.columns if str(column).lower() == "close"), None)
    if close_column is None:
        return None
    working = frame[[close_column]].dropna().copy()
    if working.empty:
        return None
    try:
        working.index = pd.to_datetime(working.index)
    except Exception:
        return None
    if getattr(working.index, "tz", None) is not None:
        working.index = working.index.tz_convert(None)
    eligible = working.loc[working.index <= timestamp]
    if eligible.empty:
        return None
    return _coerce_float(eligible.iloc[-1][close_column])


def _compute_pe_percentile(
    current_pe: float | None,
    earnings_history: pd.DataFrame | None,
    price_history: pd.DataFrame | None,
    now: datetime,
) -> float | None:
    if current_pe is None or current_pe <= 0:
        return None
    frame = _safe_frame(earnings_history)
    if frame is None or frame.empty:
        return None
    try:
        frame.index = pd.to_datetime(frame.index)
    except Exception:
        return None
    window_start = pd.Timestamp(now.date() - timedelta(days=365 * 5))
    frame = frame.sort_index()
    frame = frame.loc[frame.index >= window_start]
    if frame.empty:
        return None
    pe_values: list[float] = []
    for earnings_date, row in frame.iterrows():
        eps_actual = _coerce_float(row.get("epsActual"))
        if eps_actual is None or eps_actual <= 0:
            continue
        price = _close_on_or_before(price_history, earnings_date)
        if price is None or price <= 0:
            continue
        pe_value = price / (eps_actual * 4.0)
        if math.isfinite(pe_value) and pe_value > 0:
            pe_values.append(pe_value)
    if not pe_values:
        return None
    less_than = sum(value < current_pe for value in pe_values)
    equal_to = sum(value == current_pe for value in pe_values)
    percentile = ((less_than + 0.5 * equal_to) / len(pe_values)) * 100.0
    return round(max(0.0, min(100.0, percentile)), 2)


def _extract_statement_series(frame: pd.DataFrame | None, candidates: tuple[str, ...]) -> pd.Series | None:
    working = _safe_frame(frame)
    if working is None or working.empty:
        return None
    normalized_candidates = {_normalize_label(candidate) for candidate in candidates}
    if isinstance(working.index, pd.Index):
        for label in working.index:
            if _normalize_label(label) in normalized_candidates:
                series = working.loc[label]
                if isinstance(series, pd.Series):
                    series.index = pd.to_datetime(series.index)
                    return series.sort_index()
    if isinstance(working.columns, pd.Index):
        for label in working.columns:
            if _normalize_label(label) in normalized_candidates:
                series = working[label]
                if isinstance(series, pd.Series):
                    series.index = pd.to_datetime(series.index)
                    return series.sort_index()
    return None


def _classify_fcf_trend(values: list[float]) -> str | None:
    if len(values) < 3:
        return None
    sample = values[-3:]
    mean_value = sum(abs(value) for value in sample) / len(sample)
    tolerance = max(mean_value * 0.05, 1.0)
    if max(sample) - min(sample) <= tolerance:
        return "flat"
    if sample[0] <= sample[1] <= sample[2] and sample[2] - sample[0] > tolerance:
        return "improving"
    if sample[0] >= sample[1] >= sample[2] and sample[0] - sample[2] > tolerance:
        return "deteriorating"
    if sample[2] - sample[0] > tolerance and sample[2] >= sample[1]:
        return "improving"
    if sample[0] - sample[2] > tolerance and sample[2] <= sample[1]:
        return "deteriorating"
    return "flat"


def _extract_fcf_trend(cash_flow: pd.DataFrame | None) -> str | None:
    operating_cash_flow = _extract_statement_series(cash_flow, _OPERATING_CASHFLOW_KEYS)
    capital_expenditures = _extract_statement_series(cash_flow, _CAPEX_KEYS)
    if operating_cash_flow is None or capital_expenditures is None:
        return None
    common_dates = sorted(set(operating_cash_flow.index).intersection(capital_expenditures.index))
    values: list[float] = []
    for quarter_end in common_dates[-3:]:
        ocf = _coerce_float(operating_cash_flow.get(quarter_end))
        capex = _coerce_float(capital_expenditures.get(quarter_end))
        if ocf is None or capex is None:
            continue
        values.append(float(ocf - abs(capex)))
    return _classify_fcf_trend(values)


def _extract_recent_recommendation_counts(upgrades_downgrades: pd.DataFrame | None, now: datetime) -> tuple[int | None, int | None]:
    frame = _safe_frame(upgrades_downgrades)
    if frame is None:
        return None, None
    if frame.empty:
        return 0, 0
    try:
        frame.index = pd.to_datetime(frame.index)
    except Exception:
        return None, None
    if getattr(frame.index, "tz", None) is None:
        frame.index = frame.index.tz_localize(UTC)
    else:
        frame.index = frame.index.tz_convert(UTC)
    cutoff = pd.Timestamp(now - timedelta(days=30))
    if cutoff.tzinfo is None:
        cutoff = cutoff.tz_localize(UTC)
    else:
        cutoff = cutoff.tz_convert(UTC)
    recent = frame.loc[frame.index >= cutoff]
    if recent.empty:
        return 0, 0
    action_column = next((column for column in recent.columns if str(column).lower() == "action"), None)
    if action_column is None:
        return None, None
    upgrades = 0
    downgrades = 0
    for action in recent[action_column].fillna(""):
        normalized = str(action).strip().lower()
        if normalized in {"up", "upgrade", "upgraded", "raised", "raise"}:
            upgrades += 1
        elif normalized in {"down", "downgrade", "downgraded", "lowered", "lower"}:
            downgrades += 1
    return upgrades, downgrades


def _extract_cik(info: dict[str, Any]) -> str | None:
    for key in ("cik", "CIK", "secCik"):
        value = info.get(key)
        if value is None:
            continue
        digits = "".join(character for character in str(value) if character.isdigit())
        if digits:
            return digits.zfill(10)
    return None


def _fetch_sec_companyfacts(cik: str) -> dict[str, Any] | None:
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
    response = httpx.get(
        url,
        headers={
            "User-Agent": SEC_USER_AGENT,
            "Accept": "application/json",
        },
        timeout=10.0,
    )
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, dict) else None


def _fetch_alpha_vantage_overview(symbol: str, key: str) -> dict[str, Any]:
    try:
        response = httpx.get(
            ALPHA_VANTAGE_BASE_URL,
            params={"function": "OVERVIEW", "symbol": symbol, "apikey": key},
            timeout=10.0,
        )
        response.raise_for_status()
        payload = response.json()
        data = payload if isinstance(payload, dict) else {}
        logger.warning(
            "[%s] Alpha Vantage OVERVIEW returned keys: %s. "
            "TrailingPE=%s QuarterlyRevenueGrowthYOY=%s GrossProfitTTM=%s",
            symbol,
            list(data.keys())[:8],
            data.get("TrailingPE"),
            data.get("QuarterlyRevenueGrowthYOY") or data.get("RevenueGrowthYOY"),
            data.get("GrossProfitTTM"),
        )
        return data
    except Exception as exc:
        logger.warning(
            "[%s] Alpha Vantage OVERVIEW fetch raised %s: %s",
            symbol,
            type(exc).__name__,
            exc,
        )
        return {}


def _fetch_yahoo_search_name(symbol: str) -> str | None:
    try:
        response = httpx.get(
            YAHOO_SEARCH_URL,
            params={
                "q": symbol,
                "quotesCount": 10,
                "newsCount": 0,
                "enableFuzzyQuery": False,
                "quotesQueryId": "tss_match_phrase_query",
            },
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=5.0,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        logger.warning("[%s] Yahoo search company-name fallback failed: %s", symbol, exc)
        return None

    quotes = payload.get("quotes", []) if isinstance(payload, dict) else []
    target = symbol.strip().upper()
    for quote in quotes:
        if not isinstance(quote, dict):
            continue
        if str(quote.get("symbol", "")).strip().upper() != target:
            continue
        name = quote.get("longname") or quote.get("shortname")
        if isinstance(name, str) and name.strip():
            return name.strip()

    for quote in quotes:
        if not isinstance(quote, dict):
            continue
        if quote.get("quoteType") != "EQUITY":
            continue
        name = quote.get("longname") or quote.get("shortname")
        if isinstance(name, str) and name.strip():
            return name.strip()
    return None


def _quarterly_sec_records(companyfacts: dict[str, Any] | None, concepts: tuple[str, ...]) -> list[dict[str, Any]]:
    if not companyfacts:
        return []
    facts = companyfacts.get("facts", {}).get("us-gaap", {})
    for concept in concepts:
        concept_block = facts.get(concept)
        if not isinstance(concept_block, dict):
            continue
        units = concept_block.get("units", {})
        for values in units.values():
            if not isinstance(values, list):
                continue
            quarterly: dict[str, dict[str, Any]] = {}
            for item in values:
                if not isinstance(item, dict):
                    continue
                start = _safe_timestamp(item.get("start"))
                end = _safe_timestamp(item.get("end"))
                val = _coerce_float(item.get("val"))
                if start is None or end is None or val is None:
                    continue
                duration_days = int((end - start).days)
                fiscal_period = str(item.get("fp", "")).upper()
                if fiscal_period and not fiscal_period.startswith("Q") and duration_days > 120:
                    continue
                if duration_days < 60 or duration_days > 120:
                    continue
                key = end.date().isoformat()
                existing = quarterly.get(key)
                filed = _safe_timestamp(item.get("filed")) or end
                if existing is None or filed > (_safe_timestamp(existing.get("filed")) or end):
                    quarterly[key] = {"end": end, "filed": filed, "val": val, "fp": fiscal_period}
            if quarterly:
                return sorted(quarterly.values(), key=lambda record: record["end"])
    return []


def _latest_sec_record(companyfacts: dict[str, Any] | None, concepts: tuple[str, ...]) -> dict[str, Any] | None:
    records = _quarterly_sec_records(companyfacts, concepts)
    return records[-1] if records else None


def _sec_revenue_growth(companyfacts: dict[str, Any] | None) -> float | None:
    records = _quarterly_sec_records(companyfacts, _REVENUE_KEYS)
    if len(records) < 5:
        return None
    latest = records[-1]
    prior = next(
        (
            candidate
            for candidate in reversed(records[:-1])
            if candidate["fp"] == latest["fp"] or 280 <= (latest["end"] - candidate["end"]).days <= 380
        ),
        None,
    )
    if prior is None or prior["val"] == 0:
        return None
    growth = ((latest["val"] / prior["val"]) - 1.0) * 100.0
    return round(growth, 2)


def _sec_gross_margin(companyfacts: dict[str, Any] | None) -> float | None:
    revenue = _latest_sec_record(companyfacts, _REVENUE_KEYS)
    gross_profit = _latest_sec_record(companyfacts, _GROSS_PROFIT_KEYS)
    if revenue is None or gross_profit is None or revenue["val"] == 0:
        return None
    if revenue["end"] != gross_profit["end"]:
        return None
    return round((gross_profit["val"] / revenue["val"]) * 100.0, 2)


def _sec_fcf_trend(companyfacts: dict[str, Any] | None) -> str | None:
    operating_records = _quarterly_sec_records(companyfacts, ("NetCashProvidedByUsedInOperatingActivities",))
    capex_records = _quarterly_sec_records(companyfacts, ("PaymentsToAcquirePropertyPlantAndEquipment", "PropertyPlantAndEquipmentAdditions"))
    if not operating_records or not capex_records:
        return None
    capex_by_end = {record["end"].date().isoformat(): record["val"] for record in capex_records}
    values: list[float] = []
    for record in operating_records:
        end_key = record["end"].date().isoformat()
        capex = capex_by_end.get(end_key)
        if capex is None:
            continue
        values.append(record["val"] - abs(capex))
    return _classify_fcf_trend(values)


def _sec_as_of(companyfacts: dict[str, Any] | None) -> str | None:
    for concepts in (_EPS_KEYS, _REVENUE_KEYS):
        latest = _latest_sec_record(companyfacts, concepts)
        if latest is not None:
            return latest["end"].date().isoformat()
    return None


def _sec_pe_ratio(companyfacts: dict[str, Any] | None, current_price: float | None) -> float | None:
    if current_price is None or current_price <= 0:
        return None
    eps_records = _quarterly_sec_records(companyfacts, _EPS_KEYS)
    if len(eps_records) < 4:
        return None
    ttm_eps = sum(record["val"] for record in eps_records[-4:] if record["val"] is not None)
    if ttm_eps <= 0:
        return None
    return round(current_price / ttm_eps, 2)


def fetch_fundamentals(symbol: str) -> FundamentalsData:
    now = _utc_now()
    try:
        yf = _load_yfinance()
        ticker = yf.Ticker(symbol)
    except Exception:
        return FundamentalsData()

    try:
        info = ticker.info or {}
        logger.warning(
            "[%s] yfinance .info returned %d keys. "
            "trailingPE=%s revenueGrowth=%s grossMargins=%s priceToBook=%s",
            symbol,
            len(info),
            info.get("trailingPE"),
            info.get("revenueGrowth"),
            info.get("grossMargins"),
            info.get("priceToBook"),
        )
    except Exception as exc:
        logger.warning("[%s] yfinance .info fetch raised: %s", symbol, exc)
        info = {}
    company_name = info.get("longName") or info.get("shortName") or None

    try:
        earnings_history = ticker.earnings_history
    except Exception:
        earnings_history = None

    try:
        upgrades_downgrades = ticker.upgrades_downgrades
    except Exception:
        upgrades_downgrades = None

    try:
        quarterly_cash_flow = getattr(ticker, "quarterly_cash_flow", None)
        if quarterly_cash_flow is None:
            quarterly_cash_flow = getattr(ticker, "quarterly_cashflow", None)
    except Exception:
        quarterly_cash_flow = None

    try:
        price_history = ticker.history(period="5y", interval="1d", auto_adjust=False)
    except Exception:
        price_history = None

    eps_surprise_pct, earnings_as_of = _extract_latest_surprise(earnings_history)
    current_pe = _coerce_float(info.get("trailingPE"))
    pb_ratio = _coerce_float(info.get("priceToBook"))
    ps_ratio = _coerce_float(info.get("priceToSalesTrailingTwelveMonths"))
    ev_ebitda = _coerce_float(info.get("enterpriseToEbitda"))
    pe_percentile = _compute_pe_percentile(current_pe, earnings_history, price_history, now)
    upgrades, downgrades = _extract_recent_recommendation_counts(upgrades_downgrades, now)
    revenue_growth = _maybe_percent(info.get("revenueGrowth"))
    gross_margin = _maybe_percent(info.get("grossMargins"))
    fcf_trend = _extract_fcf_trend(_safe_frame(quarterly_cash_flow))
    current_price = _extract_current_price(info, _safe_frame(price_history))

    sec_companyfacts: dict[str, Any] | None = None
    if None in (revenue_growth, gross_margin, fcf_trend, earnings_as_of, current_pe):
        cik = _extract_cik(info)
        if cik is not None:
            try:
                sec_companyfacts = _fetch_sec_companyfacts(cik)
            except Exception:
                sec_companyfacts = None

    if current_pe is None:
        current_pe = _sec_pe_ratio(sec_companyfacts, current_price)
        pe_percentile = _compute_pe_percentile(current_pe, earnings_history, price_history, now)
    if revenue_growth is None:
        revenue_growth = _sec_revenue_growth(sec_companyfacts)
    if gross_margin is None:
        gross_margin = _sec_gross_margin(sec_companyfacts)
    if fcf_trend is None:
        fcf_trend = _sec_fcf_trend(sec_companyfacts)
    if earnings_as_of is None:
        earnings_as_of = _sec_as_of(sec_companyfacts)

    av_key = os.getenv("ALPHA_VANTAGE_KEY")
    av: dict[str, Any] = {}
    if av_key and any(value is None for value in (current_pe, revenue_growth, gross_margin, fcf_trend)):
        try:
            av = _fetch_alpha_vantage_overview(symbol, av_key)
        except Exception as exc:
            logger.warning("Alpha Vantage overview fallback failed for %s: %s", symbol, exc)
            av = {}
        if current_pe is None:
            current_pe = _coerce_float(av.get("TrailingPE"))
            pe_percentile = _compute_pe_percentile(current_pe, earnings_history, price_history, now)
        if pb_ratio is None:
            pb_ratio = _coerce_float(av.get("PriceToBookRatio"))
        if ps_ratio is None:
            ps_ratio = _coerce_float(av.get("PriceToSalesRatioTTM"))
        if ev_ebitda is None:
            ev_ebitda = _coerce_float(av.get("EVToEBITDA"))
        if revenue_growth is None:
            revenue_growth = _maybe_percent(
                av.get("QuarterlyRevenueGrowthYOY") or av.get("RevenueGrowthYOY")
            )
        if gross_margin is None:
            gross_profit = _coerce_float(av.get("GrossProfitTTM"))
            revenue_ttm = _coerce_float(av.get("RevenueTTM"))
            if gross_profit is not None and revenue_ttm and revenue_ttm > 0:
                gross_margin = round(gross_profit / revenue_ttm * 100.0, 2)

    if company_name is None:
        company_name = _fetch_yahoo_search_name(symbol)
    if company_name is None and av:
        av_name = av.get("Name")
        if isinstance(av_name, str) and av_name.strip():
            company_name = av_name.strip()

    logger.warning(
        "[%s] fundamentals final state — pe=%s revenue_growth=%s "
        "gross_margin=%s pb=%s ev_ebitda=%s",
        symbol,
        current_pe,
        revenue_growth,
        gross_margin,
        pb_ratio,
        ev_ebitda,
    )

    freshness: Literal["quarterly", "missing"] = "quarterly" if any(
        value is not None
        for value in (
            eps_surprise_pct,
            current_pe,
            revenue_growth,
            gross_margin,
            fcf_trend,
            earnings_as_of,
        )
    ) else "missing"

    return FundamentalsData(
        eps_surprise_pct=eps_surprise_pct,
        pe_ratio=round(current_pe, 2) if current_pe is not None else None,
        pb_ratio=round(pb_ratio, 2) if pb_ratio is not None else None,
        ps_ratio=round(ps_ratio, 2) if ps_ratio is not None else None,
        ev_ebitda=round(ev_ebitda, 2) if ev_ebitda is not None else None,
        pe_percentile_5y=pe_percentile,
        revenue_growth_yoy_pct=revenue_growth,
        fcf_trend=fcf_trend,
        gross_margin_pct=gross_margin,
        analyst_upgrades_30d=upgrades,
        analyst_downgrades_30d=downgrades,
        freshness=freshness,
        as_of=earnings_as_of,
        company_name=company_name,
    )


def normalize_fundamentals(fundamentals: SharedFundamentals | None) -> SharedFundamentals:
    return fundamentals or SharedFundamentals()
