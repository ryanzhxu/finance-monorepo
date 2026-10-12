from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from backtesting.data_coverage_report import _latest_period_summary
from backtesting.free_price_audit import audit_free_price_run
from backtesting.sec_edgar_audit import DEFAULT_SAMPLE_LIMIT, audit_sec_edgar_cache


def build_sec_batch_progress_report(
    *,
    batch_manifest_path: Path,
    free_price_cache_dir: Path,
    free_price_run_id: str,
    sec_cache_dir: Path,
    sample_limit: int = DEFAULT_SAMPLE_LIMIT,
) -> dict[str, Any]:
    manifest = _read_json_object(batch_manifest_path)
    batch_status = str(manifest.get("status", "unknown"))
    free_price_audit = audit_free_price_run(free_price_cache_dir, free_price_run_id)
    universe_path = free_price_cache_dir / "runs" / free_price_run_id / "universe.json"
    sec_audit = audit_sec_edgar_cache(sec_cache_dir, universe_path=universe_path, sample_limit=sample_limit)

    requested_symbols = _read_symbol_list(manifest, "requested_symbols")
    completed_symbols = sorted(_read_record_mapping(manifest, "completed"))
    failed_symbols = _string_mapping(manifest.get("failed_symbols"))
    missing_companyfacts = _string_mapping(manifest.get("missing_companyfacts"))
    unmapped_symbols = _string_mapping(manifest.get("unmapped_symbols"))
    pending_symbols = _read_symbol_list(manifest, "pending_symbols")
    universe_reference = _required_mapping(sec_audit, "universe_reference")
    latest_period = _latest_period_summary(sec_audit)

    report = {
        "schema_version": "sec_batch_progress_report_v1",
        "generated_at": _iso_now(),
        "report_scope": {
            "mode": "cache_only",
            "batch_manifest_path": str(batch_manifest_path),
            "free_price_run_id": free_price_run_id,
            "sample_limit": sample_limit,
            "free_price_cache_dir": str(free_price_cache_dir),
            "sec_cache_dir": str(sec_cache_dir),
        },
        "batch_run": {
            "run_id": manifest.get("run_id"),
            "source": manifest.get("source"),
            "status": batch_status,
            "failure_class": _manifest_failure_class(manifest, batch_status),
            "generated_at": manifest.get("generated_at"),
            "completed_at": manifest.get("completed_at"),
            "requested_symbols": requested_symbols,
            "completed_symbols": completed_symbols,
            "failed_symbols": failed_symbols,
            "missing_companyfacts_symbols": sorted(missing_companyfacts),
            "unmapped_symbols": sorted(unmapped_symbols),
            "pending_symbols": pending_symbols,
            "counts": {
                "requested_symbols": len(requested_symbols),
                "completed_symbols": len(completed_symbols),
                "failed_symbols": len(failed_symbols),
                "missing_companyfacts_symbols": len(missing_companyfacts),
                "unmapped_symbols": len(unmapped_symbols),
                "pending_symbols": len(pending_symbols),
                "observation_count": _safe_int(manifest.get("observation_count")),
            },
            "systemic_failure": _manifest_systemic_failure(manifest, batch_status),
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
        "artifact_fingerprints": {
            "batch_manifest_sha256": _sha256_file(batch_manifest_path),
            "requested_symbols_sha256": _fingerprint(requested_symbols),
            "free_price_manifest_sha256": free_price_audit.get("manifest_sha256"),
            "free_price_universe_sha256": free_price_audit.get("universe_sha256"),
            "free_price_cache_fingerprint_sha256": free_price_audit.get("cache_fingerprint_sha256"),
            "sec_ticker_mapping_sha256": _required_mapping(sec_audit, "cache_inventory").get("ticker_mapping_sha256"),
            "sec_companyfacts_content_sha256": _required_mapping(sec_audit, "cache_inventory").get("companyfacts_content_sha256"),
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
        "coverage": {
            "price_universe_symbols": int(_required_mapping(free_price_audit, "symbol_counts").get("universe", 0)),
            "sec_mapped_universe_symbols": int(universe_reference["mapped_to_sec"]),
            "sec_cached_companyfacts_symbols": int(universe_reference["cached_companyfacts"]),
            "sec_uncached_mapped_symbols": int(universe_reference["uncached_companyfacts"]),
            "sec_unmapped_universe_symbols": int(universe_reference["unmapped_symbols"]),
            "sample_uncached_mapped_symbols": list(universe_reference.get("sample_uncached_symbols", [])),
            "sample_unmapped_universe_symbols": list(universe_reference.get("sample_unmapped_symbols", [])),
            "latest_cached_period": latest_period,
        },
        "limitations": _combined_limitations(free_price_audit, sec_audit),
        "next_action": _next_action(manifest),
    }
    report["report_fingerprint_sha256"] = _fingerprint(
        {
            "batch_run": report["batch_run"],
            "artifact_fingerprints": report["artifact_fingerprints"],
            "certification_state": report["certification_state"],
            "coverage": report["coverage"],
        }
    )
    return report


def _combined_limitations(free_price_audit: dict[str, Any], sec_audit: dict[str, Any]) -> list[str]:
    limitations: list[str] = []
    for source in (free_price_audit.get("limitations"), sec_audit.get("limitations")):
        if not isinstance(source, list):
            continue
        for entry in source:
            if isinstance(entry, str) and entry not in limitations:
                limitations.append(entry)
    return limitations


def _next_action(manifest: dict[str, Any]) -> str:
    next_action = manifest.get("next_action")
    status = str(manifest.get("status", "unknown"))
    if isinstance(next_action, str) and next_action.strip() and status != "completed":
        return next_action
    return (
        "If a later explicit SEC batch is approved, rebuild the ranked uncached queue from the current cache, "
        "request at most 100 remaining uncached mapped symbols, and stop immediately on any systemic failure."
    )


def _manifest_failure_class(manifest: dict[str, Any], status: str) -> str | None:
    if status == "completed":
        return None
    value = manifest.get("failure_class")
    return str(value) if isinstance(value, str) and value.strip() else None


def _manifest_systemic_failure(manifest: dict[str, Any], status: str) -> dict[str, Any] | None:
    if status == "completed":
        return None
    value = manifest.get("systemic_failure")
    return value if isinstance(value, dict) else None


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON file: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object required: {path}")
    return payload


def _read_symbol_list(payload: dict[str, Any], key: str) -> list[str]:
    value = payload.get(key)
    if not isinstance(value, list):
        return []
    return sorted({str(item).upper() for item in value if isinstance(item, str) and item.strip()})


def _read_record_mapping(payload: dict[str, Any], key: str) -> dict[str, dict[str, Any]]:
    value = payload.get(key)
    if not isinstance(value, dict):
        return {}
    normalized = {str(symbol).upper(): record for symbol, record in value.items() if isinstance(record, dict)}
    if len(normalized) != len(value):
        raise ValueError(f"{key} must map symbols to objects")
    return normalized


def _string_mapping(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    normalized = {str(symbol).upper(): str(error) for symbol, error in value.items() if isinstance(symbol, str)}
    if len(normalized) != len(value):
        raise ValueError("symbol mapping keys must be strings")
    return normalized


def _required_mapping(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"missing object field: {key}")
    return value


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _fingerprint(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _iso_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
