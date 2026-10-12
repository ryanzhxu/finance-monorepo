from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backtesting.sec_edgar import build_sec_fundamental_observations

REVENUE_TAGS = {
    "Revenues",
    "SalesRevenueNet",
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "SalesRevenueGoodsNet",
}
NET_INCOME_TAGS = {"NetIncomeLoss", "ProfitLoss"}
OPERATING_INCOME_TAGS = {"OperatingIncomeLoss"}
EPS_TAGS = {"EarningsPerShareDiluted"}
EQUITY_TAGS = {
    "StockholdersEquity",
    "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
}
BALANCE_SHEET_TAGS = {"Assets", "Liabilities", *EQUITY_TAGS}
QUARTERLY_FORMS = {"10-Q"}
ANNUAL_FORMS = {"10-K", "20-F", "40-F"}
DEFAULT_SAMPLE_LIMIT = 25


def audit_sec_edgar_cache(
    cache_dir: Path,
    *,
    universe_path: Path | None = None,
    sample_limit: int = DEFAULT_SAMPLE_LIMIT,
) -> dict[str, Any]:
    ticker_mapping_path = cache_dir / "company_tickers.json"
    by_symbol, by_cik = _read_ticker_mapping(ticker_mapping_path)
    universe = _read_universe(universe_path)
    companyfacts_dir = cache_dir / "companyfacts"
    companyfacts_entries = sorted(path for path in companyfacts_dir.glob("*.json") if path.is_file())

    period_rows: list[dict[str, Any]] = []
    symbol_summaries: list[dict[str, Any]] = []
    file_entries: list[tuple[str, str, int]] = []
    cached_ciks: set[str] = set()

    for path in companyfacts_entries:
        cik = path.stem
        payload = _read_json_object(path)
        symbol = by_cik.get(cik)
        observations = build_sec_fundamental_observations(payload, symbol=symbol)
        period_groups = _period_groups(observations)
        period_rows.extend(period_groups)
        symbol_summaries.append(_summarize_symbol(symbol or cik, cik, period_groups, observations))
        cached_ciks.add(cik)
        file_entries.append((path.name, _sha256_file(path), path.stat().st_size))

    period_totals = _period_totals(period_rows)
    missing_feature_counts = Counter()
    period_type_counts = Counter()
    for row in period_rows:
        period_type_counts[str(row["period_type"])] += 1
        for feature in row["missing_features"]:
            missing_feature_counts[feature] += 1

    period_samples = _recent_period_samples(period_rows, limit=sample_limit)
    symbol_gap_samples = _symbol_gap_samples(symbol_summaries, limit=sample_limit)

    universe_summary = _universe_summary(universe, by_symbol, cached_ciks, sample_limit=sample_limit)
    return {
        "schema_version": "sec_edgar_cache_audit_v1",
        "audited_at": datetime.now(timezone.utc).isoformat(),
        "cache_dir": str(cache_dir),
        "source_provenance": {
            "source": "SEC EDGAR companyfacts cache",
            "point_in_time_fundamentals": True,
            "price_forecast_certified": False,
            "availability_policy": "next_business_day_after_filing",
            "note": (
                "SEC filing dates make fundamentals point-in-time aware, but cached companyfacts alone do not certify "
                "historical universe membership, delisted coverage, or price-side promotion readiness."
            ),
        },
        "cache_inventory": {
            "ticker_mapping_present": ticker_mapping_path.is_file(),
            "ticker_mapping_sha256": _sha256_file(ticker_mapping_path) if ticker_mapping_path.is_file() else None,
            "mapped_symbol_count": len(by_symbol),
            "companyfacts_file_count": len(companyfacts_entries),
            "companyfacts_content_sha256": _entries_fingerprint(file_entries),
        },
        "universe_reference": universe_summary,
        "symbol_period_coverage": {
            "symbol_count": len(symbol_summaries),
            "symbol_period_count": len(period_rows),
            "complete_feature_input_periods": period_totals["complete_feature_input_periods"],
            "quarterly_periods": period_type_counts["quarterly"],
            "annual_periods": period_type_counts["annual"],
            "other_periods": period_type_counts["other"],
            "missing_feature_counts": {
                "revenue": missing_feature_counts["revenue"],
                "net_income": missing_feature_counts["net_income"],
                "operating_income": missing_feature_counts["operating_income"],
                "eps": missing_feature_counts["eps"],
                "balance_sheet_core": missing_feature_counts["balance_sheet_core"],
            },
        },
        "recent_period_coverage": period_samples,
        "sample_symbol_period_gaps": symbol_gap_samples,
        "limitations": [
            "This audit measures only cached SEC companyfacts payloads present locally on disk.",
            "Universe symbols without a cached companyfacts payload are unresolved coverage gaps, not proof that EDGAR has no data.",
            "Current-listings universes remain survivorship-biased until a historical membership source is added.",
            "SEC fundamentals improve filing-date discipline but do not certify price-side promotion readiness.",
        ],
    }


def _read_ticker_mapping(path: Path) -> tuple[dict[str, str], dict[str, str]]:
    if not path.is_file():
        return {}, {}
    payload = _read_json_object(path)
    by_symbol: dict[str, str] = {}
    by_cik: dict[str, str] = {}
    for record in payload.values():
        if not isinstance(record, dict):
            continue
        symbol = str(record.get("ticker", "")).upper().strip()
        cik_digits = "".join(character for character in str(record.get("cik_str", "")) if character.isdigit())
        if not symbol or not cik_digits:
            continue
        cik = cik_digits.zfill(10)
        by_symbol[symbol] = cik
        by_cik[cik] = symbol
    return by_symbol, by_cik


def _read_universe(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    payload = _read_json_object(path)
    symbols = payload.get("symbols")
    if not isinstance(symbols, list) or not all(isinstance(symbol, str) and symbol for symbol in symbols):
        raise ValueError("universe symbols must be a non-empty list of strings")
    return {
        "path": str(path),
        "source": payload.get("source"),
        "symbol_count": len(symbols),
        "symbols": sorted({symbol.upper() for symbol in symbols}),
    }


def _universe_summary(
    universe: dict[str, Any] | None,
    by_symbol: dict[str, str],
    cached_ciks: set[str],
    *,
    sample_limit: int,
) -> dict[str, Any] | None:
    if universe is None:
        return None
    symbols = list(universe["symbols"])
    mapped = [symbol for symbol in symbols if symbol in by_symbol]
    cached = [symbol for symbol in mapped if by_symbol[symbol] in cached_ciks]
    uncached = [symbol for symbol in mapped if by_symbol[symbol] not in cached_ciks]
    unmapped = [symbol for symbol in symbols if symbol not in by_symbol]
    return {
        "path": universe["path"],
        "source": universe.get("source"),
        "symbol_count": universe["symbol_count"],
        "mapped_to_sec": len(mapped),
        "cached_companyfacts": len(cached),
        "uncached_companyfacts": len(uncached),
        "unmapped_symbols": len(unmapped),
        "sample_uncached_symbols": uncached[:sample_limit],
        "sample_unmapped_symbols": unmapped[:sample_limit],
    }


def _period_groups(observations: list[Any]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for observation in observations:
        if observation.report_date is None:
            continue
        period_type = _period_type(observation.form)
        period_label = _period_label(observation.report_date, period_type)
        key = (period_label, period_type)
        group = grouped.setdefault(
            key,
            {
                "period": period_label,
                "period_type": period_type,
                "report_date": observation.report_date.isoformat(),
                "tags": set(),
                "available_on": observation.available_on.isoformat(),
                "accessions": set(),
            },
        )
        group["tags"].add(observation.tag)
        group["available_on"] = max(str(group["available_on"]), observation.available_on.isoformat())
        if observation.accession_number:
            group["accessions"].add(observation.accession_number)
    rows: list[dict[str, Any]] = []
    for (period_label, period_type), group in sorted(grouped.items(), reverse=True):
        tags = set(group["tags"])
        missing = _missing_features(tags)
        rows.append(
            {
                "period": period_label,
                "period_type": period_type,
                "report_date": group["report_date"],
                "available_on": group["available_on"],
                "missing_features": missing,
                "complete_feature_inputs": not missing,
                "accession_count": len(group["accessions"]),
            }
        )
    return rows


def _summarize_symbol(symbol: str, cik: str, period_groups: list[dict[str, Any]], observations: list[Any]) -> dict[str, Any]:
    missing_counts = Counter()
    for row in period_groups:
        for feature in row["missing_features"]:
            missing_counts[feature] += 1
    latest_gap = next((row for row in period_groups if row["missing_features"]), None)
    latest_period = period_groups[0]["period"] if period_groups else None
    return {
        "symbol": symbol,
        "cik": cik,
        "observation_count": len(observations),
        "period_count": len(period_groups),
        "complete_feature_input_periods": sum(1 for row in period_groups if row["complete_feature_inputs"]),
        "latest_period": latest_period,
        "latest_gap_period": latest_gap["period"] if latest_gap else None,
        "latest_gap_missing_features": latest_gap["missing_features"] if latest_gap else [],
        "missing_feature_counts": {
            "revenue": missing_counts["revenue"],
            "net_income": missing_counts["net_income"],
            "operating_income": missing_counts["operating_income"],
            "eps": missing_counts["eps"],
            "balance_sheet_core": missing_counts["balance_sheet_core"],
        },
    }


def _period_totals(period_rows: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "complete_feature_input_periods": sum(1 for row in period_rows if row["complete_feature_inputs"]),
    }


def _recent_period_samples(period_rows: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], dict[str, Any]] = defaultdict(
        lambda: {
            "symbol_periods": 0,
            "complete_feature_input_symbols": 0,
            "missing_feature_counts": Counter(),
        }
    )
    for row in period_rows:
        key = (str(row["period"]), str(row["period_type"]))
        bucket = grouped[key]
        bucket["symbol_periods"] += 1
        if row["complete_feature_inputs"]:
            bucket["complete_feature_input_symbols"] += 1
        for feature in row["missing_features"]:
            bucket["missing_feature_counts"][feature] += 1
    samples = []
    for (period, period_type), bucket in sorted(grouped.items(), reverse=True)[:limit]:
        samples.append(
            {
                "period": period,
                "period_type": period_type,
                "symbol_periods": bucket["symbol_periods"],
                "complete_feature_input_symbols": bucket["complete_feature_input_symbols"],
                "missing_feature_counts": {
                    "revenue": bucket["missing_feature_counts"]["revenue"],
                    "net_income": bucket["missing_feature_counts"]["net_income"],
                    "operating_income": bucket["missing_feature_counts"]["operating_income"],
                    "eps": bucket["missing_feature_counts"]["eps"],
                    "balance_sheet_core": bucket["missing_feature_counts"]["balance_sheet_core"],
                },
            }
        )
    return samples


def _symbol_gap_samples(symbol_summaries: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    def sort_key(row: dict[str, Any]) -> tuple[int, int, str]:
        gap_count = sum(int(value) for value in row["missing_feature_counts"].values())
        return (gap_count, int(row["period_count"]), str(row.get("latest_gap_period") or ""))

    rows = [row for row in symbol_summaries if row["latest_gap_period"] is not None]
    rows.sort(key=sort_key, reverse=True)
    return rows[:limit]


def _missing_features(tags: set[str]) -> list[str]:
    missing: list[str] = []
    if not tags.intersection(REVENUE_TAGS):
        missing.append("revenue")
    if not tags.intersection(NET_INCOME_TAGS):
        missing.append("net_income")
    if not tags.intersection(OPERATING_INCOME_TAGS):
        missing.append("operating_income")
    if not tags.intersection(EPS_TAGS):
        missing.append("eps")
    has_equity = bool(tags.intersection(EQUITY_TAGS))
    has_assets_or_liabilities = bool(tags.intersection(BALANCE_SHEET_TAGS - EQUITY_TAGS))
    if not (has_equity and has_assets_or_liabilities):
        missing.append("balance_sheet_core")
    return missing


def _period_type(form: str) -> str:
    if form in QUARTERLY_FORMS:
        return "quarterly"
    if form in ANNUAL_FORMS:
        return "annual"
    return "other"


def _period_label(report_date: Any, period_type: str) -> str:
    if period_type == "quarterly":
        quarter = ((report_date.month - 1) // 3) + 1
        return f"{report_date.year}-Q{quarter}"
    if period_type == "annual":
        return f"{report_date.year}-FY"
    return report_date.isoformat()


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON file: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object required: {path}")
    return payload


def _entries_fingerprint(entries: list[tuple[str, str, int]]) -> str:
    canonical = "\n".join(f"{name}\t{digest}\t{size}" for name, digest, size in entries)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
