from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from backtesting.free_price_audit import audit_free_price_run

DEFAULT_BATCH_SIZE = 100
MAX_BATCHES_PER_UTC_DAY = 4
READY_PRICE_HISTORY_BUCKET = "ready_price_history"
INSUFFICIENT_HISTORY_BUCKET = "insufficient_history"
PRICE_FETCH_FAILED_BUCKET = "price_fetch_failed"
MISSING_PRICE_RECORD_BUCKET = "missing_price_manifest_record"

_STATUS_BUCKETS = {
    "completed": READY_PRICE_HISTORY_BUCKET,
    "reused_cache": READY_PRICE_HISTORY_BUCKET,
    "insufficient_history": INSUFFICIENT_HISTORY_BUCKET,
    "failed": PRICE_FETCH_FAILED_BUCKET,
}

_BUCKET_PRIORITY = {
    READY_PRICE_HISTORY_BUCKET: 0,
    INSUFFICIENT_HISTORY_BUCKET: 1,
    PRICE_FETCH_FAILED_BUCKET: 2,
    MISSING_PRICE_RECORD_BUCKET: 3,
}


def build_sec_collection_queue_report(
    *,
    free_price_cache_dir: Path,
    free_price_run_id: str,
    sec_cache_dir: Path,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> dict[str, Any]:
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")

    free_price_audit = audit_free_price_run(free_price_cache_dir, free_price_run_id)
    universe_path = free_price_cache_dir / "runs" / free_price_run_id / "universe.json"
    manifest = _read_json_object(free_price_cache_dir / "runs" / free_price_run_id / "manifest.json")
    universe = _read_json_object(universe_path)
    universe_symbols = _read_symbols(universe)
    records = _read_records(manifest)
    by_symbol = _read_ticker_mapping(sec_cache_dir / "company_tickers.json")
    companyfacts_entries = _companyfacts_entries(sec_cache_dir / "companyfacts")
    cached_ciks = {entry[0].removesuffix(".json") for entry in companyfacts_entries}
    mapped_symbols = [symbol for symbol in universe_symbols if symbol in by_symbol]
    cached_symbols = [symbol for symbol in mapped_symbols if by_symbol[symbol]["cik"] in cached_ciks]
    unmapped_symbols = [symbol for symbol in universe_symbols if symbol not in by_symbol]
    run_summaries = _read_run_summaries(sec_cache_dir / "runs")
    batch_execution_gate = _build_batch_execution_gate(run_summaries)

    ranked_uncached_symbols: list[dict[str, Any]] = []
    queue_status_counts: Counter[str] = Counter()
    priority_counts: Counter[str] = Counter()

    for symbol in universe_symbols:
        mapping = by_symbol.get(symbol)
        if mapping is None:
            continue
        if mapping["cik"] in cached_ciks:
            continue
        record = records.get(symbol, {})
        price_status = str(record.get("status", "missing_record"))
        priority_bucket = _STATUS_BUCKETS.get(price_status, MISSING_PRICE_RECORD_BUCKET)
        rows = _safe_int(record.get("rows"))
        entry = {
            "symbol": symbol,
            "cik": mapping["cik"],
            "title": mapping.get("title"),
            "price_status": price_status,
            "priority_bucket": priority_bucket,
            "priority_order": _BUCKET_PRIORITY[priority_bucket],
            "price_rows": rows,
            "price_from": record.get("from"),
            "price_through": record.get("through"),
            "price_cache_file": record.get("cache_file"),
            "price_record_present": bool(record),
            "rate_limited": bool(record.get("rate_limited")) if record else False,
        }
        ranked_uncached_symbols.append(entry)
        queue_status_counts[price_status] += 1
        priority_counts[priority_bucket] += 1

    ranked_uncached_symbols.sort(
        key=lambda entry: (
            int(entry["priority_order"]),
            -int(entry["price_rows"]),
            str(entry["symbol"]),
        )
    )
    for rank, entry in enumerate(ranked_uncached_symbols, start=1):
        entry["rank"] = rank
        del entry["priority_order"]

    top_batch = ranked_uncached_symbols[:batch_size]
    top_batch_symbols = [entry["symbol"] for entry in top_batch]

    report = {
        "schema_version": "sec_collection_queue_report_v2",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "report_scope": {
            "mode": "cache_only",
            "free_price_run_id": free_price_run_id,
            "batch_size": batch_size,
            "free_price_cache_dir": str(free_price_cache_dir),
            "sec_cache_dir": str(sec_cache_dir),
        },
        "sources": {
            "price_history": {
                "source": free_price_audit.get("source"),
                "universe_source": free_price_audit.get("universe_source"),
            },
            "sec_fundamentals": {
                "source": "SEC EDGAR companyfacts cache",
                "availability_policy": "next_business_day_after_filing",
            },
        },
        "artifact_fingerprints": {
            "free_price_manifest_sha256": free_price_audit.get("manifest_sha256"),
            "free_price_universe_sha256": free_price_audit.get("universe_sha256"),
            "free_price_cache_fingerprint_sha256": free_price_audit.get("cache_fingerprint_sha256"),
            "sec_ticker_mapping_sha256": _sha256_file(sec_cache_dir / "company_tickers.json"),
            "sec_companyfacts_content_sha256": _entries_fingerprint(companyfacts_entries),
        },
        "certification_state": {
            "point_in_time_fundamentals": True,
            "price_point_in_time_certified": bool(_required_mapping(free_price_audit, "source_provenance").get("point_in_time_certified")),
            "universe_membership_point_in_time": bool(
                _required_mapping(free_price_audit, "source_provenance").get("universe_membership_point_in_time")
            ),
            "forecast_promotion_eligible": False,
        },
        "coverage_context": {
            "price_universe_symbols": int(_required_mapping(free_price_audit, "symbol_counts").get("universe", 0)),
            "sec_mapped_universe_symbols": len(mapped_symbols),
            "sec_cached_companyfacts_symbols": len(cached_symbols),
            "sec_uncached_mapped_symbols": len(ranked_uncached_symbols),
            "sec_unmapped_universe_symbols": len(unmapped_symbols),
        },
        "batch_execution_gate": batch_execution_gate,
        "queue_summary": {
            "requested_symbol_count": len(ranked_uncached_symbols),
            "candidate_batch_size": len(top_batch),
            "deferred_symbol_count": max(len(ranked_uncached_symbols) - len(top_batch), 0),
            "completed_symbols": [],
            "failed_symbols": {},
            "failure_class": None,
            "price_status_counts": dict(sorted(queue_status_counts.items())),
            "priority_bucket_counts": dict(sorted(priority_counts.items())),
        },
        "ranking_rules": [
            "Only universe symbols mapped to SEC and still missing a cached companyfacts payload are eligible.",
            "Symbols with ready price history (`completed` or `reused_cache`) rank before `insufficient_history`, then `failed`, then missing manifest records.",
            "Within the same priority bucket, symbols with more cached price rows rank earlier; alphabetical order breaks ties.",
            "This report does not fetch SEC data and does not treat uncached or unmapped symbols as filing-period feature gaps.",
        ],
        "candidate_batch_symbols": top_batch_symbols,
        "ranked_uncached_symbols": ranked_uncached_symbols,
        "run_history": run_summaries,
        "next_action": _next_action(batch_execution_gate),
    }
    report["report_fingerprint_sha256"] = _fingerprint(
        {
            "artifact_fingerprints": report["artifact_fingerprints"],
            "batch_execution_gate": report["batch_execution_gate"],
            "coverage_context": report["coverage_context"],
            "queue_summary": report["queue_summary"],
            "candidate_batch_symbols": report["candidate_batch_symbols"],
        }
    )
    return report


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON file: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"JSON object required: {path}")
    return payload


def _read_symbols(universe: dict[str, Any]) -> list[str]:
    symbols = universe.get("symbols")
    if not isinstance(symbols, list) or not all(isinstance(symbol, str) and symbol for symbol in symbols):
        raise ValueError("universe symbols must be a non-empty list of strings")
    return sorted({symbol.upper() for symbol in symbols})


def _read_records(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    records = manifest.get("records")
    if not isinstance(records, dict):
        raise ValueError("manifest records must be an object")
    normalized = {str(symbol).upper(): record for symbol, record in records.items() if isinstance(record, dict)}
    if len(normalized) != len(records):
        raise ValueError("manifest records must map symbols to objects")
    return normalized


def _read_symbol_list(payload: dict[str, Any], key: str) -> list[str]:
    value = payload.get(key)
    if not isinstance(value, list):
        return []
    return sorted({str(item).upper() for item in value if isinstance(item, str) and item.strip()})


def _read_ticker_mapping(path: Path) -> dict[str, dict[str, str | None]]:
    if not path.is_file():
        return {}
    payload = _read_json_object(path)
    mapping: dict[str, dict[str, str | None]] = {}
    for record in payload.values():
        if not isinstance(record, dict):
            continue
        symbol = str(record.get("ticker", "")).upper().strip()
        cik_digits = "".join(character for character in str(record.get("cik_str", "")) if character.isdigit())
        if not symbol or not cik_digits:
            continue
        mapping[symbol] = {
            "cik": cik_digits.zfill(10),
            "title": str(record.get("title")) if record.get("title") is not None else None,
        }
    return mapping


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


def _fingerprint(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _companyfacts_entries(companyfacts_dir: Path) -> list[tuple[str, str, int]]:
    entries: list[tuple[str, str, int]] = []
    if not companyfacts_dir.is_dir():
        return entries
    for path in sorted(companyfacts_dir.glob("*.json")):
        if not path.is_file():
            continue
        entries.append((path.name, _sha256_file(path), path.stat().st_size))
    return entries


def _entries_fingerprint(entries: list[tuple[str, str, int]]) -> str:
    canonical = "\n".join(f"{name}\t{digest}\t{size}" for name, digest, size in entries)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_run_summaries(runs_dir: Path) -> list[dict[str, Any]]:
    if not runs_dir.is_dir():
        return []
    summaries: list[dict[str, Any]] = []
    for manifest_path in sorted(runs_dir.glob("*/manifest.json")):
        manifest = _read_json_object(manifest_path)
        run_id = manifest.get("run_id")
        pending_symbols = _read_symbol_list(manifest, "pending_symbols")
        requested_symbols = _read_symbol_list(manifest, "requested_symbols")
        summary = {
            "run_id": str(run_id) if isinstance(run_id, str) and run_id.strip() else manifest_path.parent.name,
            "status": str(manifest.get("status", "pending")),
            "generated_at": manifest.get("generated_at"),
            "completed_at": manifest.get("completed_at"),
            "requested_symbol_count": len(requested_symbols),
            "pending_symbol_count": len(pending_symbols),
            "failure_class": manifest.get("failure_class"),
            "manifest_path": str(manifest_path),
        }
        summaries.append(summary)
    summaries.sort(key=lambda summary: (str(summary.get("generated_at") or ""), str(summary.get("run_id") or "")), reverse=True)
    return summaries


def _build_batch_execution_gate(run_summaries: list[dict[str, Any]]) -> dict[str, Any]:
    utc_day = datetime.now(timezone.utc).date()
    started_today_run_ids: list[str] = []
    blocking_run_ids: list[str] = []
    blocking_reasons: list[str] = []

    for summary in run_summaries:
        run_id = str(summary.get("run_id") or "")
        generated_day = _utc_calendar_day(summary.get("generated_at"))
        if generated_day == utc_day:
            started_today_run_ids.append(run_id)
        status = str(summary.get("status", "pending"))
        pending_symbol_count = _safe_int(summary.get("pending_symbol_count"))
        if pending_symbol_count <= 0:
            continue
        if status == "systemic_failure":
            blocking_run_ids.append(run_id)
            blocking_reasons.append(f"{run_id} stopped on systemic_failure and still has pending symbols")
            continue
        if status != "completed":
            blocking_run_ids.append(run_id)
            blocking_reasons.append(f"{run_id} is unresolved with pending symbols")

    eligible_for_new_batch = True
    blocking_reason: str | None = None
    if blocking_reasons:
        eligible_for_new_batch = False
        blocking_reason = "; ".join(blocking_reasons)
    elif len(started_today_run_ids) >= MAX_BATCHES_PER_UTC_DAY:
        eligible_for_new_batch = False
        blocking_reason = (
            f"UTC day {utc_day.isoformat()} already has {len(started_today_run_ids)} SEC batch starts; "
            f"do not exceed the cap of {MAX_BATCHES_PER_UTC_DAY}."
        )

    return {
        "calendar_day_basis": "UTC generated_at date",
        "calendar_day": utc_day.isoformat(),
        "max_batches_per_calendar_day": MAX_BATCHES_PER_UTC_DAY,
        "calendar_day_started_run_count": len(started_today_run_ids),
        "calendar_day_started_run_ids": started_today_run_ids,
        "blocking_run_ids": blocking_run_ids,
        "eligible_for_new_batch": eligible_for_new_batch,
        "blocking_reason": blocking_reason,
    }


def _next_action(batch_execution_gate: dict[str, Any]) -> str:
    if not bool(batch_execution_gate.get("eligible_for_new_batch")):
        blocking_reason = batch_execution_gate.get("blocking_reason")
        return (
            f"Do not start a new SEC batch. {blocking_reason} "
            "Clear the unresolved run or wait for a later UTC day before using `candidate_batch_symbols`."
        )
    return (
        "If a later explicit SEC batch is approved, request only `candidate_batch_symbols`, keep the remaining "
        "ranked queue deferred, and stop immediately on systemic failure before retrying after a recovery check."
    )


def _utc_calendar_day(value: Any) -> date | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        timestamp = datetime.fromisoformat(value)
    except ValueError:
        return None
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc).date()
