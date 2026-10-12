from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import date, datetime, timezone
from typing import Any

import httpx
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, model_validator

SEC_COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
SUPPORTED_FORMS = {"10-K", "10-Q", "20-F", "40-F"}
DEFAULT_FACT_TAGS = {
    "Revenues",
    "SalesRevenueNet",
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "SalesRevenueGoodsNet",
    "NetIncomeLoss",
    "ProfitLoss",
    "OperatingIncomeLoss",
    "Assets",
    "Liabilities",
    "StockholdersEquity",
    "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    "Assets",
    "EarningsPerShareDiluted",
}


class SecFundamentalObservation(BaseModel):
    """A reported fundamental, usable only after a conservative filing-date delay."""

    model_config = ConfigDict(extra="forbid")

    cik: str = Field(pattern=r"^\d{10}$")
    symbol: str | None = None
    tag: str = Field(min_length=1)
    unit: str = Field(min_length=1)
    value: float
    form: str
    period_start: date | None = None
    report_date: date | None = None
    filed_on: date
    available_on: date
    accession_number: str | None = None

    @model_validator(mode="after")
    def validate_availability(self) -> SecFundamentalObservation:
        if self.available_on <= self.filed_on:
            raise ValueError("SEC fundamental must become available after its filing date")
        return self


class SecEdgarProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "sec_edgar_fundamentals_provenance_v1"
    source: str = "SEC EDGAR companyfacts"
    retrieved_at: datetime
    symbols: list[str]
    ciks: list[str]
    raw_cache_files: list[str] = Field(default_factory=list)
    point_in_time_fundamentals: bool = True
    price_forecast_certified: bool = False
    availability_policy: str = "next_business_day_after_filing"
    note: str = (
        "SEC filing dates make fundamentals point-in-time aware, but EDGAR does not by itself provide "
        "a survivorship-free historical price universe or certify price forecasts."
    )


JsonGetter = Callable[..., dict[str, Any]]


def resolve_sec_ciks(symbols: Iterable[str], *, get_json: JsonGetter) -> dict[str, str]:
    payload = get_json(SEC_COMPANY_TICKERS_URL)
    records = payload.values() if isinstance(payload, dict) else []
    by_symbol = {
        str(record.get("ticker", "")).upper(): str(record.get("cik_str", "")).zfill(10)
        for record in records
        if isinstance(record, dict) and str(record.get("ticker", "")).strip() and str(record.get("cik_str", "")).isdigit()
    }
    return {symbol.upper(): by_symbol[symbol.upper()] for symbol in symbols if symbol.upper() in by_symbol}


def fetch_sec_json(url: str, *, user_agent: str, timeout_seconds: float = 30.0) -> dict[str, Any]:
    if not user_agent.strip():
        raise ValueError("SEC_EDGAR_USER_AGENT or --user-agent is required")
    response = httpx.get(
        url,
        headers={"User-Agent": user_agent, "Accept": "application/json"},
        timeout=timeout_seconds,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("SEC response must be a JSON object")
    return payload


def build_sec_fundamental_observations(
    payload: dict[str, Any],
    *,
    symbol: str | None = None,
    allowed_tags: set[str] | None = None,
) -> list[SecFundamentalObservation]:
    cik = _normalize_cik(payload.get("cik"))
    if cik is None:
        raise ValueError("SEC companyfacts payload is missing a valid CIK")
    tags = allowed_tags or DEFAULT_FACT_TAGS
    us_gaap = payload.get("facts", {}).get("us-gaap", {})
    if not isinstance(us_gaap, dict):
        return []
    observations: list[SecFundamentalObservation] = []
    seen: set[tuple[str, str, str, date | None, str | None]] = set()
    for tag, definition in us_gaap.items():
        if tag not in tags or not isinstance(definition, dict):
            continue
        units = definition.get("units", {})
        if not isinstance(units, dict):
            continue
        for unit, facts in units.items():
            if not isinstance(facts, list):
                continue
            for fact in facts:
                observation = _observation_from_fact(cik, symbol, str(tag), str(unit), fact)
                if observation is None:
                    continue
                key = (
                    observation.tag,
                    observation.unit,
                    observation.filed_on.isoformat(),
                    observation.report_date,
                    observation.accession_number,
                )
                if key not in seen:
                    seen.add(key)
                    observations.append(observation)
    return sorted(observations, key=lambda item: (item.available_on, item.tag, item.unit, item.accession_number or ""))


def build_sec_edgar_provenance(
    observations: Iterable[SecFundamentalObservation],
    *,
    raw_cache_files: Iterable[str] = (),
) -> SecEdgarProvenance:
    rows = list(observations)
    return SecEdgarProvenance(
        retrieved_at=datetime.now(timezone.utc),
        symbols=sorted({item.symbol for item in rows if item.symbol}),
        ciks=sorted({item.cik for item in rows}),
        raw_cache_files=sorted(set(raw_cache_files)),
    )


def _observation_from_fact(
    cik: str,
    symbol: str | None,
    tag: str,
    unit: str,
    fact: object,
) -> SecFundamentalObservation | None:
    if not isinstance(fact, dict) or str(fact.get("form", "")) not in SUPPORTED_FORMS:
        return None
    filed_on = _parse_date(fact.get("filed"))
    value = fact.get("val")
    if filed_on is None or not isinstance(value, (int, float)):
        return None
    report_date = _parse_date(fact.get("end"))
    return SecFundamentalObservation(
        cik=cik,
        symbol=symbol.upper() if symbol else None,
        tag=tag,
        unit=unit,
        value=float(value),
        form=str(fact["form"]),
        period_start=_parse_date(fact.get("start")),
        report_date=report_date,
        filed_on=filed_on,
        available_on=_next_business_day(filed_on),
        accession_number=str(fact["accn"]) if fact.get("accn") else None,
    )


def _next_business_day(value: date) -> date:
    return (pd.Timestamp(value) + pd.offsets.BDay(1)).date()


def _parse_date(value: object) -> date | None:
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _normalize_cik(value: object) -> str | None:
    digits = "".join(character for character in str(value or "") if character.isdigit())
    return digits.zfill(10) if digits else None
