from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import date
from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from backtesting.forecast import ForecastObservation
from backtesting.sec_edgar import SecFundamentalObservation

SEC_FUNDAMENTAL_FEATURE_SCHEMA = "sec_fundamentals_v1"
COMBINED_FEATURE_SCHEMA = "continuous_regime_sec_fundamentals_v1"


class SecFundamentalFeatureSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accessions: list[str] = Field(default_factory=list)
    available_on: date


class SecFundamentalFeatureSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    as_of: date
    symbol: str
    feature_schema_version: Literal["sec_fundamentals_v1"] = SEC_FUNDAMENTAL_FEATURE_SCHEMA
    feature_values: dict[str, float]
    feature_sources: dict[str, SecFundamentalFeatureSource]


def build_sec_fundamental_feature_snapshots(
    symbol: str,
    as_of_dates: Iterable[date],
    observations: Iterable[SecFundamentalObservation],
) -> list[SecFundamentalFeatureSnapshot]:
    """Build only from filings whose conservative available_on date has passed."""

    rows = sorted(
        [item for item in observations if item.symbol == symbol.upper()],
        key=lambda item: (item.available_on, item.report_date or date.min, item.accession_number or ""),
    )
    snapshots: list[SecFundamentalFeatureSnapshot] = []
    visible: list[SecFundamentalObservation] = []
    row_index = 0
    for as_of in sorted(set(as_of_dates)):
        while row_index < len(rows) and rows[row_index].available_on <= as_of:
            visible.append(rows[row_index])
            row_index += 1
        feature_values, sources = _feature_values(as_of, visible)
        if feature_values:
            snapshots.append(
                SecFundamentalFeatureSnapshot(
                    as_of=as_of,
                    symbol=symbol.upper(),
                    feature_values=feature_values,
                    feature_sources=sources,
                )
            )
    return snapshots


def attach_sec_fundamental_features(
    observations: Iterable[ForecastObservation],
    snapshots: Iterable[SecFundamentalFeatureSnapshot],
) -> tuple[list[ForecastObservation], dict[str, int]]:
    by_key = {(item.symbol, item.as_of): item for item in snapshots}
    combined: list[ForecastObservation] = []
    skipped: dict[str, int] = {}
    required = set(_required_feature_names())
    for observation in observations:
        snapshot = by_key.get((observation.symbol, observation.as_of))
        if snapshot is None or not required.issubset(snapshot.feature_values):
            skipped["missing_sec_fundamentals"] = skipped.get("missing_sec_fundamentals", 0) + 1
            continue
        values = {**observation.feature_values, **snapshot.feature_values}
        if any(not np.isfinite(value) for value in values.values()):
            skipped["invalid_sec_fundamentals"] = skipped.get("invalid_sec_fundamentals", 0) + 1
            continue
        combined.append(
            observation.model_copy(
                update={
                    "feature_schema_version": COMBINED_FEATURE_SCHEMA,
                    "feature_values": values,
                }
            )
        )
    return combined, skipped


def _feature_values(
    as_of: date,
    visible: list[SecFundamentalObservation],
) -> tuple[dict[str, float], dict[str, SecFundamentalFeatureSource]]:
    quarterly_revenue = _latest_duration(
        visible,
        ("Revenues", "SalesRevenueNet", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueGoodsNet"),
        minimum_days=60,
        maximum_days=120,
    )
    prior_revenue = _year_ago_match(visible, quarterly_revenue)
    quarterly_income = _latest_duration(visible, ("NetIncomeLoss", "ProfitLoss"), minimum_days=60, maximum_days=120)
    prior_income = _year_ago_match(visible, quarterly_income)
    quarterly_operating_income = _latest_duration(visible, ("OperatingIncomeLoss",), minimum_days=60, maximum_days=120)
    quarterly_eps = _latest_duration(visible, ("EarningsPerShareDiluted",), minimum_days=60, maximum_days=120)
    prior_eps = _year_ago_match(visible, quarterly_eps)
    liabilities = _latest(visible, ("Liabilities",), units={"USD"})
    equity = _latest(
        visible,
        ("StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"),
        units={"USD"},
    )
    assets = _latest(visible, ("Assets",), units={"USD"})
    latest_filing = max(visible, key=lambda item: item.available_on, default=None)
    selected = {
        "sec_revenue_yoy": _growth(quarterly_revenue, prior_revenue),
        "sec_net_income_yoy": _growth(quarterly_income, prior_income),
        "sec_operating_margin": _ratio(quarterly_operating_income, quarterly_revenue),
        "sec_eps_yoy": _growth(quarterly_eps, prior_eps),
        "sec_liabilities_to_equity": _liabilities_to_equity(liabilities, assets, equity),
        "sec_filing_age_days": float((as_of - latest_filing.available_on).days) if latest_filing else None,
    }
    source_rows = {
        "sec_revenue_yoy": [quarterly_revenue, prior_revenue],
        "sec_net_income_yoy": [quarterly_income, prior_income],
        "sec_operating_margin": [quarterly_operating_income, quarterly_revenue],
        "sec_eps_yoy": [quarterly_eps, prior_eps],
        "sec_liabilities_to_equity": [item for item in (liabilities, assets, equity) if item is not None],
        "sec_filing_age_days": [latest_filing],
    }
    values = {name: value for name, value in selected.items() if value is not None and np.isfinite(value)}
    sources = {
        name: SecFundamentalFeatureSource(
            accessions=sorted({item.accession_number for item in rows if item and item.accession_number}),
            available_on=max(item.available_on for item in rows if item),
        )
        for name, rows in source_rows.items()
        if name in values and any(rows)
    }
    return values, sources


def _required_feature_names() -> tuple[str, ...]:
    return (
        "sec_revenue_yoy",
        "sec_net_income_yoy",
        "sec_operating_margin",
        "sec_eps_yoy",
        "sec_liabilities_to_equity",
        "sec_filing_age_days",
    )


def _latest_duration(
    rows: list[SecFundamentalObservation],
    tags: tuple[str, ...],
    *,
    minimum_days: int,
    maximum_days: int,
) -> SecFundamentalObservation | None:
    candidates = [
        item
        for item in rows
        if item.tag in tags
        and item.period_start is not None
        and item.report_date is not None
        and minimum_days <= (item.report_date - item.period_start).days <= maximum_days
    ]
    return max(candidates, key=lambda item: (item.report_date or date.min, item.available_on), default=None)


def _year_ago_match(
    rows: list[SecFundamentalObservation],
    latest: SecFundamentalObservation | None,
) -> SecFundamentalObservation | None:
    if latest is None or latest.report_date is None or latest.period_start is None:
        return None
    period_days = (latest.report_date - latest.period_start).days
    candidates = [
        item
        for item in rows
        if item.tag == latest.tag
        and item.unit == latest.unit
        and item.report_date is not None
        and item.period_start is not None
        and 300 <= (latest.report_date - item.report_date).days <= 430
        and abs((item.report_date - item.period_start).days - period_days) <= 15
    ]
    return max(candidates, key=lambda item: item.report_date or date.min, default=None)


def _latest(rows: list[SecFundamentalObservation], tags: tuple[str, ...], *, units: set[str]) -> SecFundamentalObservation | None:
    return max(
        [item for item in rows if item.tag in tags and item.unit in units],
        key=lambda item: (item.report_date or date.min, item.available_on),
        default=None,
    )


def _growth(current: SecFundamentalObservation | None, prior: SecFundamentalObservation | None) -> float | None:
    if current is None or prior is None or prior.value == 0:
        return None
    return round(current.value / abs(prior.value) - 1, 6)


def _ratio(numerator: SecFundamentalObservation | None, denominator: SecFundamentalObservation | None) -> float | None:
    if numerator is None or denominator is None or denominator.value == 0:
        return None
    return round(numerator.value / denominator.value, 6)


def _liabilities_to_equity(
    liabilities: SecFundamentalObservation | None,
    assets: SecFundamentalObservation | None,
    equity: SecFundamentalObservation | None,
) -> float | None:
    if equity is None or equity.value == 0:
        return None
    if liabilities is not None:
        return _ratio(liabilities, equity)
    if assets is None:
        return None
    return round((assets.value - equity.value) / equity.value, 6)
