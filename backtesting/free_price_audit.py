from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backtesting.free_price_cache import cache_path

DEFAULT_BENCHMARK_SYMBOLS = ("SPY", "QQQ", "^VIX")


def audit_free_price_run(
    cache_dir: Path,
    run_id: str,
    *,
    benchmark_symbols: tuple[str, ...] = DEFAULT_BENCHMARK_SYMBOLS,
) -> dict[str, Any]:
    """Create a cache-only integrity report for one frozen free-price run."""

    run_dir = cache_dir / "runs" / run_id
    manifest_path = run_dir / "manifest.json"
    universe_path = run_dir / "universe.json"
    manifest = _read_json_object(manifest_path)
    universe = _read_json_object(universe_path)
    symbols = _read_symbols(universe)
    records = _read_records(manifest)
    missing_record_symbols = sorted(set(symbols) - set(records))
    unknown_record_symbols = sorted(set(records) - set(symbols))

    status_counts = Counter(str(record.get("status", "unknown")) for record in records.values())
    cache_entries = _cache_entries(cache_dir, records)
    benchmark_entries = _benchmark_entries(cache_dir, benchmark_symbols)
    fingerprint = _fingerprint(manifest_path, universe_path, cache_entries, benchmark_entries)

    return {
        "schema_version": "free_price_cache_audit_v1",
        "audited_at": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "source": manifest.get("source"),
        "universe_source": manifest.get("universe_source"),
        "requested": manifest.get("requested"),
        "source_provenance": {
            "adjustment_mode": "auto_adjusted_current_view",
            "point_in_time_certified": False,
            "corporate_actions_available_as_of": False,
            "universe_membership_point_in_time": False,
            "note": "Yahoo/yfinance adjusted prices and a current-listings universe remain experimental only.",
        },
        "manifest_sha256": _sha256_file(manifest_path),
        "universe_sha256": _sha256_file(universe_path),
        "symbol_counts": {
            "universe": len(symbols),
            "records": len(records),
            "missing_records": len(missing_record_symbols),
            "unknown_records": len(unknown_record_symbols),
        },
        "status_counts": dict(sorted(status_counts.items())),
        "cache_files": cache_entries,
        "benchmarks": benchmark_entries,
        "cache_fingerprint_sha256": fingerprint,
        "reproducible_cache_only": not missing_record_symbols
        and not unknown_record_symbols
        and not cache_entries["missing_files"],
        "limitations": list(manifest.get("limitations", [])),
    }


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
    return symbols


def _read_records(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    records = manifest.get("records")
    if not isinstance(records, dict):
        raise ValueError("manifest records must be an object")
    normalized = {str(symbol): record for symbol, record in records.items() if isinstance(record, dict)}
    if len(normalized) != len(records):
        raise ValueError("manifest records must map symbols to objects")
    return normalized


def _cache_entries(cache_dir: Path, records: dict[str, dict[str, Any]]) -> dict[str, Any]:
    entries: list[tuple[str, str, int]] = []
    missing_files: list[str] = []
    for symbol, record in sorted(records.items()):
        cache_file = record.get("cache_file")
        if not isinstance(cache_file, str) or not cache_file:
            continue
        path = cache_dir / cache_file
        if path.name != cache_file or not path.is_file():
            missing_files.append(symbol)
            continue
        entries.append((cache_file, _sha256_file(path), path.stat().st_size))
    return {
        "referenced_file_count": len(entries),
        "referenced_total_bytes": sum(entry[2] for entry in entries),
        "referenced_content_sha256": _entries_fingerprint(entries),
        "missing_files": missing_files,
    }


def _benchmark_entries(cache_dir: Path, symbols: tuple[str, ...]) -> dict[str, Any]:
    entries: list[tuple[str, str, int]] = []
    missing: list[str] = []
    for symbol in symbols:
        path = cache_path(cache_dir, symbol)
        if not path.is_file():
            missing.append(symbol)
            continue
        entries.append((symbol, _sha256_file(path), path.stat().st_size))
    return {
        "symbols": list(symbols),
        "available_count": len(entries),
        "missing_symbols": missing,
        "content_sha256": _entries_fingerprint(entries),
    }


def _fingerprint(manifest_path: Path, universe_path: Path, cache_entries: dict[str, Any], benchmark_entries: dict[str, Any]) -> str:
    payload = {
        "manifest_sha256": _sha256_file(manifest_path),
        "universe_sha256": _sha256_file(universe_path),
        "cache_content_sha256": cache_entries["referenced_content_sha256"],
        "benchmark_content_sha256": benchmark_entries["content_sha256"],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _entries_fingerprint(entries: list[tuple[str, str, int]]) -> str:
    canonical = "\n".join(f"{name}\t{digest}\t{size}" for name, digest, size in entries)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
