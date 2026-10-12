from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backtesting.free_price_audit import audit_free_price_run
from backtesting.sec_edgar_audit import DEFAULT_SAMPLE_LIMIT, audit_sec_edgar_cache


def build_stock_coverage_bias_report(
    *,
    free_price_cache_dir: Path,
    free_price_run_id: str,
    sec_cache_dir: Path,
    sample_limit: int = DEFAULT_SAMPLE_LIMIT,
) -> dict[str, Any]:
    free_price_audit = audit_free_price_run(free_price_cache_dir, free_price_run_id)
    universe_path = free_price_cache_dir / "runs" / free_price_run_id / "universe.json"
    sec_audit = audit_sec_edgar_cache(sec_cache_dir, universe_path=universe_path, sample_limit=sample_limit)

    universe_reference = _required_mapping(sec_audit, "universe_reference")
    latest_period = _latest_period_summary(sec_audit)
    uncached_companyfacts = int(universe_reference["uncached_companyfacts"])
    unmapped_symbols = int(universe_reference["unmapped_symbols"])
    latest_period_missing_symbols = latest_period["symbols_with_missing_features"]

    report = {
        "schema_version": "stock_data_coverage_bias_report_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "report_scope": {
            "mode": "cache_only",
            "free_price_run_id": free_price_run_id,
            "sample_limit": sample_limit,
            "free_price_cache_dir": str(free_price_cache_dir),
            "sec_cache_dir": str(sec_cache_dir),
        },
        "sources": {
            "price_history": {
                "source": free_price_audit.get("source"),
                "universe_source": free_price_audit.get("universe_source"),
            },
            "sec_fundamentals": {
                "source": _required_mapping(sec_audit, "source_provenance").get("source"),
                "availability_policy": _required_mapping(sec_audit, "source_provenance").get("availability_policy"),
            },
        },
        "certification_state": {
            "point_in_time_fundamentals": bool(_required_mapping(sec_audit, "source_provenance").get("point_in_time_fundamentals")),
            "price_point_in_time_certified": bool(_required_mapping(free_price_audit, "source_provenance").get("point_in_time_certified")),
            "corporate_actions_available_as_of": bool(
                _required_mapping(free_price_audit, "source_provenance").get("corporate_actions_available_as_of")
            ),
            "universe_membership_point_in_time": bool(
                _required_mapping(free_price_audit, "source_provenance").get("universe_membership_point_in_time")
            ),
            "forecast_promotion_eligible": False,
        },
        "artifact_fingerprints": {
            "free_price_manifest_sha256": free_price_audit.get("manifest_sha256"),
            "free_price_universe_sha256": free_price_audit.get("universe_sha256"),
            "free_price_cache_fingerprint_sha256": free_price_audit.get("cache_fingerprint_sha256"),
            "sec_ticker_mapping_sha256": _required_mapping(sec_audit, "cache_inventory").get("ticker_mapping_sha256"),
            "sec_companyfacts_content_sha256": _required_mapping(sec_audit, "cache_inventory").get("companyfacts_content_sha256"),
        },
        "coverage_split": {
            "price_universe_symbols": int(_required_mapping(free_price_audit, "symbol_counts").get("universe", 0)),
            "price_manifest_records": int(_required_mapping(free_price_audit, "symbol_counts").get("records", 0)),
            "price_status_counts": dict(_required_mapping(free_price_audit, "status_counts")),
            "sec_mapped_universe_symbols": int(universe_reference["mapped_to_sec"]),
            "sec_cached_companyfacts_symbols": int(universe_reference["cached_companyfacts"]),
            "sec_uncached_mapped_symbols": uncached_companyfacts,
            "sec_unmapped_universe_symbols": unmapped_symbols,
            "sample_uncached_mapped_symbols": list(universe_reference.get("sample_uncached_symbols", [])),
            "sample_unmapped_universe_symbols": list(universe_reference.get("sample_unmapped_symbols", [])),
        },
        "filing_gap_analysis": {
            "cached_sec_symbol_count": int(_required_mapping(sec_audit, "symbol_period_coverage").get("symbol_count", 0)),
            "cached_sec_symbol_period_count": int(_required_mapping(sec_audit, "symbol_period_coverage").get("symbol_period_count", 0)),
            "complete_feature_input_periods": int(
                _required_mapping(sec_audit, "symbol_period_coverage").get("complete_feature_input_periods", 0)
            ),
            "latest_period": latest_period,
            "sample_symbols_with_feature_gaps": list(sec_audit.get("sample_symbol_period_gaps", [])),
        },
        "bias_summary": {
            "unresolved_coverage_gaps_are_separate_from_feature_gaps": True,
            "uncached_mapped_symbols_requiring_future_sec_collection": uncached_companyfacts,
            "unmapped_symbols_requiring_separate_resolution": unmapped_symbols,
            "latest_period_symbols_with_true_feature_gaps": latest_period_missing_symbols,
            "survivorship_bias_present": True,
            "corporate_action_history_not_certified": True,
        },
        "limitations": _combined_limitations(free_price_audit, sec_audit),
        "next_action": (
            "If a later explicit SEC batch is approved, target only uncached mapped symbols, keep unmapped symbols in a "
            "separate queue, and do not treat either category as a filing-period feature gap."
        ),
    }
    report["report_fingerprint_sha256"] = _fingerprint(
        {
            "artifact_fingerprints": report["artifact_fingerprints"],
            "coverage_split": report["coverage_split"],
            "filing_gap_analysis": report["filing_gap_analysis"],
            "certification_state": report["certification_state"],
        }
    )
    return report


def _latest_period_summary(sec_audit: dict[str, Any]) -> dict[str, Any]:
    recent_periods = sec_audit.get("recent_period_coverage")
    if not isinstance(recent_periods, list) or not recent_periods:
        return {
            "period": None,
            "period_type": None,
            "symbol_periods": 0,
            "complete_feature_input_symbols": 0,
            "symbols_with_missing_features": 0,
            "missing_feature_counts": {
                "revenue": 0,
                "net_income": 0,
                "operating_income": 0,
                "eps": 0,
                "balance_sheet_core": 0,
            },
        }
    latest = recent_periods[0]
    symbol_periods = int(latest.get("symbol_periods", 0))
    complete = int(latest.get("complete_feature_input_symbols", 0))
    return {
        "period": latest.get("period"),
        "period_type": latest.get("period_type"),
        "symbol_periods": symbol_periods,
        "complete_feature_input_symbols": complete,
        "symbols_with_missing_features": max(symbol_periods - complete, 0),
        "missing_feature_counts": dict(latest.get("missing_feature_counts", {})),
    }


def _combined_limitations(free_price_audit: dict[str, Any], sec_audit: dict[str, Any]) -> list[str]:
    limitations: list[str] = []
    for source in (free_price_audit.get("limitations"), sec_audit.get("limitations")):
        if not isinstance(source, list):
            continue
        for entry in source:
            if isinstance(entry, str) and entry not in limitations:
                limitations.append(entry)
    return limitations


def _required_mapping(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"missing object field: {key}")
    return value


def _fingerprint(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
