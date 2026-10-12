from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Mapping

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtesting.sec_edgar import (
    SEC_COMPANYFACTS_URL,
    build_sec_edgar_provenance,
    build_sec_fundamental_observations,
    fetch_sec_json,
    resolve_sec_ciks,
)
from backtesting.sec_edgar_cache import (
    DEFAULT_SEC_EDGAR_CACHE_DIR,
    companyfacts_cache_path,
    read_cached_json,
    ticker_mapping_cache_path,
    write_cached_json,
)

TERMINAL_STATUSES = {"completed", "missing_companyfacts", "unmapped_symbol"}
SYSTEMIC_FAILURE_CLASSES = {"auth", "dns", "rate_limit", "transport"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download point-in-time SEC filing fundamentals for explicit symbols or CIKs")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--symbols", help="Comma-separated US ticker symbols")
    source.add_argument("--symbols-file", type=Path, help="File containing comma- or newline-separated US ticker symbols")
    source.add_argument("--ciks", help="Comma-separated SEC CIKs")
    parser.add_argument("--output", type=Path, required=True, help="JSONL fundamental observations")
    parser.add_argument("--provenance-output", type=Path, required=True)
    parser.add_argument("--manifest-output", type=Path)
    parser.add_argument("--run-id", help="Stable run identifier used for resume and private manifest paths")
    parser.add_argument("--resume", action="store_true", help="Resume only symbols not already terminal in the saved manifest")
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_SEC_EDGAR_CACHE_DIR)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--minimum-request-interval", type=float, default=0.12)
    parser.add_argument("--user-agent", default=os.getenv("SEC_EDGAR_USER_AGENT"))
    return parser.parse_args()


def main() -> int:
    load_dotenv(ROOT / ".env")
    args = parse_args()
    user_agent = args.user_agent or os.getenv("SEC_EDGAR_USER_AGENT", "")
    if not user_agent.strip():
        raise SystemExit("set SEC_EDGAR_USER_AGENT to a descriptive contact string before downloading from SEC EDGAR")
    if args.minimum_request_interval < 0.1:
        raise SystemExit("--minimum-request-interval must be at least 0.1 seconds")
    _validate_args(args)
    manifest_path = _manifest_path(args)
    get_json = _throttled_get_json(user_agent, args.minimum_request_interval)
    requested_symbols = _requested_symbols(args)
    manifest, frozen_symbols, ciks_by_symbol = _load_or_create_run(args, manifest_path, requested_symbols, get_json)
    records = _records_from_manifest(manifest)
    for symbol in frozen_symbols:
        if records.get(symbol, {}).get("status") in TERMINAL_STATUSES:
            continue
        cik = ciks_by_symbol.get(symbol)
        if cik is None:
            continue
        try:
            payload, cache_file = _companyfacts_payload(args, cik, get_json)
        except (httpx.HTTPError, ValueError) as error:
            failure = _classify_failure(error)
            record = {
                "status": failure["status"],
                "cik": cik,
                "error": f"{type(error).__name__}: {error}",
                "failure_class": failure["failure_class"],
                "failed_at": _now(),
            }
            if failure["next_action"] is not None:
                record["next_action"] = failure["next_action"]
            records[symbol] = record
            manifest["records"] = records
            _refresh_manifest_indexes(manifest)
            if failure["failure_class"] in SYSTEMIC_FAILURE_CLASSES:
                _write_partial_manifest(
                    manifest_path,
                    manifest,
                    cache_dir=args.cache_dir,
                    failure_class=str(failure["failure_class"]),
                    symbol=symbol,
                    cik=cik,
                    error=record["error"],
                    failed_at=str(record["failed_at"]),
                    next_action=str(failure["next_action"]),
                )
                return 1
            _write_json(manifest_path, manifest)
            continue
        symbol_observations = build_sec_fundamental_observations(payload, symbol=None if symbol == cik else symbol)
        records[symbol] = {
            "status": "completed",
            "cik": cik,
            "cache_file": cache_file,
            "observation_count": len(symbol_observations),
            "completed_at": _now(),
        }
        manifest["records"] = records
        _refresh_manifest_indexes(manifest)
        _write_json(manifest_path, manifest)

    observations, raw_cache_files = _collect_observations_from_manifest(manifest, args.cache_dir)
    provenance = build_sec_edgar_provenance(observations, raw_cache_files=raw_cache_files)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.provenance_output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("".join(item.model_dump_json() + "\n" for item in observations), encoding="utf-8")
    args.provenance_output.write_text(provenance.model_dump_json(indent=2) + "\n", encoding="utf-8")
    _write_completed_manifest(
        manifest_path,
        manifest,
        cache_dir=args.cache_dir,
        observations=len(observations),
        raw_cache_files=raw_cache_files,
        provenance_output=args.provenance_output,
        output=args.output,
    )
    print(
        json.dumps(
            {
                "run_id": manifest["run_id"],
                "symbols": frozen_symbols,
                "observations": len(observations),
                "failed_symbols": manifest["failed_symbols"],
                "pending_symbols": manifest["pending_symbols"],
                "manifest": str(manifest_path),
                "provenance": provenance.model_dump(mode="json"),
            },
            indent=2,
        )
    )
    return 0


def _csv_values(value: str | None) -> list[str]:
    return sorted({item.strip().upper() for item in (value or "").replace("\n", ",").split(",") if item.strip()})


def _requested_symbols(args: argparse.Namespace) -> list[str]:
    if args.symbols_file is not None:
        return _csv_values(args.symbols_file.read_text(encoding="utf-8"))
    return _csv_values(args.symbols)


def _normalized_cik(value: str) -> str:
    digits = "".join(character for character in value if character.isdigit())
    if not digits:
        raise SystemExit(f"invalid CIK: {value}")
    return digits.zfill(10)


def _resolve_ciks(
    args: argparse.Namespace,
    symbols: list[str],
    get_json,
    raw_cache_files: list[str],
) -> dict[str, str]:
    if not symbols:
        return {_normalized_cik(cik): _normalized_cik(cik) for cik in _csv_values(args.ciks)}
    path = ticker_mapping_cache_path(args.cache_dir)
    payload = None if args.refresh else read_cached_json(path)
    if payload is None:
        payload = get_json("https://www.sec.gov/files/company_tickers.json")
        write_cached_json(path, payload)
    raw_cache_files.append(path.relative_to(args.cache_dir).as_posix())
    return resolve_sec_ciks(symbols, get_json=lambda _url: payload)


def _companyfacts_payload(args: argparse.Namespace, cik: str, get_json) -> tuple[dict[str, Any], str]:
    path = companyfacts_cache_path(args.cache_dir, cik)
    payload = None if args.refresh else read_cached_json(path)
    if payload is None:
        payload = get_json(SEC_COMPANYFACTS_URL.format(cik=cik))
        write_cached_json(path, payload)
    return payload, path.relative_to(args.cache_dir).as_posix()


def _validate_args(args: argparse.Namespace) -> None:
    if args.resume and not args.manifest_output and not args.run_id:
        raise SystemExit("--resume requires --run-id or --manifest-output")


def _manifest_path(args: argparse.Namespace) -> Path:
    if args.manifest_output is not None:
        return args.manifest_output
    run_id = args.run_id or args.output.stem
    if not re.fullmatch(r"[A-Za-z0-9._-]+", run_id):
        raise SystemExit("--run-id may contain only letters, digits, dots, underscores, and hyphens")
    return args.cache_dir / "runs" / run_id / "manifest.json"


def _load_or_create_run(
    args: argparse.Namespace,
    manifest_path: Path,
    requested_symbols: list[str],
    get_json,
) -> tuple[dict[str, Any], list[str], dict[str, str]]:
    if args.resume:
        if not manifest_path.exists():
            raise SystemExit("--resume requires an existing manifest")
        manifest = _read_json(manifest_path)
        frozen_symbols = manifest.get("requested_symbols")
        ciks_by_symbol = manifest.get("ciks")
        if not isinstance(frozen_symbols, list) or not all(isinstance(symbol, str) for symbol in frozen_symbols):
            raise SystemExit("saved SEC manifest is missing requested_symbols")
        if not isinstance(ciks_by_symbol, dict) or not all(isinstance(symbol, str) and isinstance(cik, str) for symbol, cik in ciks_by_symbol.items()):
            raise SystemExit("saved SEC manifest is missing ciks")
        _refresh_manifest_indexes(manifest)
        return manifest, frozen_symbols, ciks_by_symbol

    if manifest_path.exists():
        raise SystemExit(f"run files already exist at {manifest_path.parent}; use --resume or choose a new --run-id")

    raw_cache_files: list[str] = []
    ciks_by_symbol = _resolve_ciks(args, requested_symbols, get_json, raw_cache_files)
    frozen_symbols = requested_symbols or sorted(ciks_by_symbol)
    manifest: dict[str, Any] = {
        "schema_version": "sec_edgar_download_manifest_v3",
        "run_id": args.run_id or manifest_path.parent.name,
        "generated_at": _now(),
        "source": "sec_edgar_companyfacts",
        "requested_symbols": frozen_symbols,
        "ciks": ciks_by_symbol,
        "ticker_mapping_cache_file": raw_cache_files[0] if raw_cache_files else None,
        "records": {
            symbol: {
                "status": "unmapped_symbol",
                "error": "symbol not found in official SEC ticker mapping",
                "recorded_at": _now(),
            }
            for symbol in requested_symbols
            if symbol not in ciks_by_symbol
        },
        "completed": {},
        "failed": {},
        "failed_symbols": {},
        "missing_companyfacts": {},
        "pending_symbols": [],
        "unmapped_symbols": {},
    }
    _refresh_manifest_indexes(manifest)
    _write_json(manifest_path, manifest)
    return manifest, frozen_symbols, ciks_by_symbol


def _records_from_manifest(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    records = manifest.get("records")
    if not isinstance(records, dict):
        manifest["records"] = {}
        return {}
    return {str(symbol): dict(record) for symbol, record in records.items() if isinstance(record, dict)}


def _refresh_manifest_indexes(manifest: dict[str, Any]) -> None:
    records = _records_from_manifest(manifest)
    requested_symbols = manifest.get("requested_symbols")
    frozen_symbols = requested_symbols if isinstance(requested_symbols, list) else sorted(records)
    manifest["records"] = records
    manifest["completed"] = {symbol: record for symbol, record in records.items() if record.get("status") == "completed"}
    manifest["failed"] = {symbol: str(record.get("error", "download failed")) for symbol, record in records.items() if record.get("status") == "failed"}
    manifest["failed_symbols"] = dict(manifest["failed"])
    manifest["missing_companyfacts"] = {
        symbol: str(record.get("error", "companyfacts payload not available"))
        for symbol, record in records.items()
        if record.get("status") == "missing_companyfacts"
    }
    manifest["unmapped_symbols"] = {
        symbol: str(record.get("error", "symbol not found in official SEC ticker mapping"))
        for symbol, record in records.items()
        if record.get("status") == "unmapped_symbol"
    }
    manifest["pending_symbols"] = [
        symbol for symbol in frozen_symbols if records.get(symbol, {}).get("status") not in TERMINAL_STATUSES
    ]


def _collect_observations_from_manifest(manifest: dict[str, Any], cache_dir: Path) -> tuple[list[Any], list[str]]:
    observations: list[Any] = []
    raw_cache_files: list[str] = []
    mapping_file = manifest.get("ticker_mapping_cache_file")
    if isinstance(mapping_file, str) and (cache_dir / mapping_file).is_file():
        raw_cache_files.append(mapping_file)
    completed = manifest.get("completed")
    if not isinstance(completed, dict):
        return observations, raw_cache_files
    for symbol, record in sorted(completed.items()):
        if not isinstance(symbol, str) or not isinstance(record, dict):
            continue
        cache_file = record.get("cache_file")
        cik = record.get("cik")
        if not isinstance(cache_file, str):
            raise SystemExit(f"completed SEC record for {symbol} is missing cache_file")
        payload = read_cached_json(cache_dir / cache_file)
        if payload is None:
            raise SystemExit(f"missing cached SEC payload for completed symbol {symbol}")
        raw_cache_files.append(cache_file)
        observations.extend(build_sec_fundamental_observations(payload, symbol=None if symbol == cik else symbol))
    return observations, sorted(set(raw_cache_files))


def _classify_failure(error: Exception) -> dict[str, str | None]:
    if isinstance(error, httpx.HTTPStatusError):
        status_code = error.response.status_code
        if status_code == 404:
            return {
                "status": "missing_companyfacts",
                "failure_class": "missing_companyfacts",
                "next_action": "No retry needed; keep this symbol counted as missing SEC companyfacts.",
            }
        if status_code in {401, 403}:
            return {
                "status": "failed",
                "failure_class": "auth",
                "next_action": "Stop the batch, verify SEC access policy and SEC_EDGAR_USER_AGENT, then rerun with --resume after a recovery check.",
            }
        if status_code == 429:
            return {
                "status": "failed",
                "failure_class": "rate_limit",
                "next_action": "Stop the batch, wait for SEC rate-limit recovery, then rerun with --resume after a recovery check.",
            }
        if status_code >= 500:
            return {
                "status": "failed",
                "failure_class": "transport",
                "next_action": "Stop the batch, verify SEC availability, then rerun with --resume after a recovery check.",
            }
    if isinstance(error, httpx.ConnectError):
        return {
            "status": "failed",
            "failure_class": "dns" if "dns" in str(error).lower() or "nodename" in str(error).lower() else "transport",
            "next_action": "Stop the batch, verify DNS/network reachability to sec.gov, then rerun with --resume after a recovery check.",
        }
    if isinstance(error, (httpx.TimeoutException, httpx.NetworkError, httpx.ProtocolError, httpx.TransportError)):
        return {
            "status": "failed",
            "failure_class": "transport",
            "next_action": "Stop the batch, verify network/transport health to sec.gov, then rerun with --resume after a recovery check.",
        }
    return {
        "status": "failed",
        "failure_class": "record_error",
        "next_action": "Inspect this symbol-specific failure before rerunning with --resume.",
    }


def _write_completed_manifest(
    manifest_path: Path,
    manifest: dict[str, Any],
    *,
    cache_dir: Path,
    observations: int,
    raw_cache_files: list[str],
    provenance_output: Path,
    output: Path,
) -> None:
    manifest["status"] = "completed"
    manifest["completed_at"] = _now()
    manifest["failure_class"] = None
    manifest["systemic_failure"] = None
    manifest["observation_count"] = observations
    manifest["raw_cache_files"] = sorted(raw_cache_files)
    manifest["raw_cache_sha256"] = {path: _sha256(cache_dir / path) for path in raw_cache_files}
    manifest["provenance"] = provenance_output.name
    manifest["output"] = output.name
    manifest["next_action"] = "Use --resume only for a later run_id; this run is complete."
    manifest["cache_counts"] = _cache_counts(manifest)
    _write_json(manifest_path, manifest)


def _write_partial_manifest(
    manifest_path: Path,
    manifest: dict[str, Any],
    *,
    cache_dir: Path,
    failure_class: str,
    symbol: str,
    cik: str,
    error: str,
    failed_at: str,
    next_action: str,
) -> None:
    raw_cache_files = _manifest_cache_files(manifest)
    manifest["status"] = "systemic_failure"
    manifest["completed_at"] = _now()
    manifest["failure_class"] = failure_class
    manifest["raw_cache_files"] = raw_cache_files
    manifest["raw_cache_sha256"] = {path: _sha256(cache_dir / path) for path in raw_cache_files}
    manifest["cache_counts"] = _cache_counts(manifest)
    manifest["next_action"] = next_action
    manifest["systemic_failure"] = {
        "symbol": symbol,
        "cik": cik,
        "failure_class": failure_class,
        "error": error,
        "failed_at": failed_at,
        "next_action": next_action,
    }
    _write_json(manifest_path, manifest)


def _manifest_cache_files(manifest: Mapping[str, Any]) -> list[str]:
    raw_cache_files: list[str] = []
    mapping_file = manifest.get("ticker_mapping_cache_file")
    if isinstance(mapping_file, str):
        raw_cache_files.append(mapping_file)
    completed = manifest.get("completed")
    if isinstance(completed, dict):
        for record in completed.values():
            if isinstance(record, dict) and isinstance(record.get("cache_file"), str):
                raw_cache_files.append(str(record["cache_file"]))
    return sorted(set(raw_cache_files))


def _cache_counts(manifest: Mapping[str, Any]) -> dict[str, int]:
    return {
        "completed_symbols": len(manifest.get("completed", {})) if isinstance(manifest.get("completed"), dict) else 0,
        "failed_symbols": len(manifest.get("failed_symbols", {})) if isinstance(manifest.get("failed_symbols"), dict) else 0,
        "missing_companyfacts_symbols": (
            len(manifest.get("missing_companyfacts", {})) if isinstance(manifest.get("missing_companyfacts"), dict) else 0
        ),
        "unmapped_symbols": len(manifest.get("unmapped_symbols", {})) if isinstance(manifest.get("unmapped_symbols"), dict) else 0,
        "raw_cache_files": len(manifest.get("raw_cache_files", [])) if isinstance(manifest.get("raw_cache_files"), list) else 0,
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _throttled_get_json(user_agent: str, minimum_interval: float):
    last_request = 0.0

    def get_json(url: str):
        nonlocal last_request
        wait_seconds = minimum_interval - (time.monotonic() - last_request)
        if wait_seconds > 0:
            time.sleep(wait_seconds)
        payload = fetch_sec_json(url, user_agent=user_agent)
        last_request = time.monotonic()
        return payload

    return get_json


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False) as handle:
        temporary_path = Path(handle.name)
        handle.write(json.dumps(value, indent=2) + "\n")
    try:
        temporary_path.replace(path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"expected JSON object in {path}")
    return payload


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
