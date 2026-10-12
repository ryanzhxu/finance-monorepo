from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backtesting.r2_storage import build_upload_plan_for_files, verify_local_round_trip


def build_stock_28_r2_roundtrip_manifest(
    *,
    key_prefix: str,
    download_root: Path,
    free_price_manifest_path: Path,
    coverage_report_path: Path,
    sec_cache_audit_path: Path,
) -> dict[str, Any]:
    coverage_report = _read_json_object(coverage_report_path)
    sec_cache_audit = _read_json_object(sec_cache_audit_path)
    free_price_manifest = _read_json_object(free_price_manifest_path)

    uploads = build_upload_plan_for_files(
        [
            (free_price_manifest_path, f"{key_prefix}/free-price-manifest.json"),
            (coverage_report_path, f"{key_prefix}/stock-28-coverage-bias-report.json"),
            (sec_cache_audit_path, f"{key_prefix}/stock-28-sec-cache-audit.json"),
        ]
    )
    verified = verify_local_round_trip(uploads, destination_dir=download_root)

    coverage_split = _required_mapping(coverage_report, "coverage_split")
    filing_gap_analysis = _required_mapping(coverage_report, "filing_gap_analysis")
    latest_period = _required_mapping(filing_gap_analysis, "latest_period")
    certification_state = _required_mapping(coverage_report, "certification_state")

    return {
        "schema_version": "stock_28_r2_roundtrip_manifest_v1",
        "validated_at": datetime.now(timezone.utc).isoformat(),
        "source": "private_cloudflare_r2_research_artifacts",
        "r2_key_prefix": key_prefix,
        "round_trip_verified": True,
        "artifacts": verified,
        "retrieval_times": {
            "free_price_manifest_generated_at": free_price_manifest.get("generated_at"),
            "coverage_report_generated_at": coverage_report.get("generated_at"),
            "sec_cache_audit_audited_at": sec_cache_audit.get("audited_at"),
        },
        "requested_symbols": {
            "price_universe_symbols": int(coverage_split.get("price_universe_symbols", 0)),
            "sec_mapped_universe_symbols": int(coverage_split.get("sec_mapped_universe_symbols", 0)),
        },
        "completed_symbols": {
            "sec_cached_companyfacts_symbols": int(coverage_split.get("sec_cached_companyfacts_symbols", 0)),
            "cached_sec_symbol_count": int(filing_gap_analysis.get("cached_sec_symbol_count", 0)),
        },
        "failed_symbols": {
            "sec_uncached_mapped_symbols": int(coverage_split.get("sec_uncached_mapped_symbols", 0)),
            "sec_unmapped_universe_symbols": int(coverage_split.get("sec_unmapped_universe_symbols", 0)),
        },
        "failure_class": "none",
        "coverage": {
            "price_status_counts": dict(coverage_split.get("price_status_counts", {})),
            "latest_period": latest_period,
            "report_fingerprint_sha256": coverage_report.get("report_fingerprint_sha256"),
            "sec_companyfacts_content_sha256": _required_mapping(coverage_report, "artifact_fingerprints").get(
                "sec_companyfacts_content_sha256"
            ),
        },
        "hashes": {
            "free_price_manifest_sha256": _artifact_sha256(verified, "free-price-manifest.json"),
            "coverage_report_sha256": _artifact_sha256(verified, "stock-28-coverage-bias-report.json"),
            "sec_cache_audit_sha256": _artifact_sha256(verified, "stock-28-sec-cache-audit.json"),
        },
        "certification_state": dict(certification_state),
        "next_action": coverage_report.get("next_action"),
    }


def _artifact_sha256(artifacts: list[dict[str, object]], suffix: str) -> str:
    for artifact in artifacts:
        key = artifact.get("key")
        if isinstance(key, str) and key.endswith(f"/{suffix}"):
            sha256 = artifact.get("sha256")
            if isinstance(sha256, str):
                return sha256
    raise ValueError(f"verified artifact missing: {suffix}")


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON file: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object required: {path}")
    return payload


def _required_mapping(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"missing object field: {key}")
    return value
