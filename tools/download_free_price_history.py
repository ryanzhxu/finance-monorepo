from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tempfile
import time
from collections import deque
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from datetime import date, datetime, timedelta, timezone
from functools import partial
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtesting.free_price_cache import DEFAULT_FREE_PRICE_CACHE_DIR, cache_path, load_or_fetch_free_adjusted_ohlcv, read_cached_ohlcv
from backtesting.free_price_dataset import fetch_free_adjusted_ohlcv
from backtesting.free_price_universe import fetch_current_us_common_symbols, load_free_price_universe_config
from backtesting.r2_storage import R2StorageSettings, build_upload_plan_for_files, create_r2_client, upload_verified_plan

TERMINAL_STATUSES = {"completed", "reused_cache", "insufficient_history", "stale"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download resumable free adjusted daily US price history")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--symbols", help="Comma-separated symbols")
    source.add_argument("--symbols-file", type=Path, help="One symbol per line or comma-separated symbols")
    source.add_argument("--nasdaq-current-common-stocks", action="store_true")
    parser.add_argument("--start", type=date.fromisoformat, default=date(1990, 1, 1))
    parser.add_argument("--end", type=date.fromisoformat, default=date.today())
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--all-symbols", action="store_true", help="Download the frozen source universe, not only a sample")
    selection.add_argument("--max-symbols", type=int)
    parser.add_argument("--sample-seed", help="Deterministic ordering seed; use a new value for an independent run")
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_FREE_PRICE_CACHE_DIR)
    parser.add_argument("--manifest-output", type=Path)
    parser.add_argument("--run-id", help="Stable run identifier used for resume and private R2 object prefixes")
    parser.add_argument("--resume", action="store_true", help="Resume only symbols not already terminal in the frozen manifest")
    parser.add_argument("--workers", type=int, help="Initial bounded worker count")
    parser.add_argument("--max-workers", type=int, help="Maximum adaptive worker count")
    parser.add_argument("--batch-size", type=int, help="Completed symbols per local/R2 checkpoint")
    parser.add_argument("--r2-checkpoints", action="store_true", help="Upload every completed batch to private R2")
    parser.add_argument("--refresh", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_free_price_universe_config()["download"]
    _validate_args(args, config)
    manifest_path = _manifest_path(args, config)
    manifest, symbols = _load_or_create_run(args, config, manifest_path)
    records = _records_from_manifest(manifest)
    pending = deque(symbol for symbol in symbols if records.get(symbol, {}).get("status") not in TERMINAL_STATUSES)
    checkpoint = _CheckpointWriter(args, config, manifest_path, manifest)
    state = _AdaptiveState(
        workers=int(args.workers or config["initial_workers"]),
        minimum_workers=int(config["minimum_workers"]),
        maximum_workers=int(args.max_workers or config["maximum_workers"]),
        window_size=int(config["adaptive_window_size"]),
        maximum_failure_rate=float(config["maximum_failure_rate"]),
        cooldown_seconds=float(config["cooldown_seconds"]),
    )
    processed = 0
    active: dict[Future[dict[str, Any]], str] = {}
    with ThreadPoolExecutor(max_workers=state.maximum_workers) as executor:
        while pending or active:
            if state.cooldown_until > time.monotonic() and not active:
                time.sleep(state.cooldown_until - time.monotonic())
            while pending and len(active) < state.workers and state.cooldown_until <= time.monotonic():
                symbol = pending.popleft()
                future = executor.submit(_download_symbol, symbol, args, config)
                active[future] = symbol
            if not active:
                continue
            completed, _ = wait(active, return_when=FIRST_COMPLETED)
            for future in completed:
                symbol = active.pop(future)
                result = future.result()
                records[symbol] = result
                manifest["records"] = records
                _refresh_manifest_indexes(manifest)
                _write_json(manifest_path, manifest)
                checkpoint.add(symbol, result)
                processed += 1
                state.observe(result, processed)
                if checkpoint.ready:
                    checkpoint.flush()

    checkpoint.flush()
    manifest["completed_at"] = datetime.now(timezone.utc).isoformat()
    _refresh_manifest_indexes(manifest)
    _write_json(manifest_path, manifest)
    if args.r2_checkpoints:
        checkpoint.upload_final_manifest()
    print(
        json.dumps(
            {
                "run_id": manifest["run_id"],
                "requested": len(symbols),
                "completed": len(manifest["completed"]),
                "failed": len(manifest["failed"]),
                "workers_final": state.workers,
                "manifest": str(manifest_path),
            },
            indent=2,
        )
    )
    return 0 if manifest["completed"] else 1


def _validate_args(args: argparse.Namespace, config: dict[str, Any]) -> None:
    if args.start > args.end:
        raise SystemExit("--start must not be after --end")
    if args.max_symbols is not None and args.max_symbols <= 0:
        raise SystemExit("--max-symbols must be positive")
    if args.batch_size is not None and args.batch_size <= 0:
        raise SystemExit("--batch-size must be positive")
    initial_workers = int(args.workers or config["initial_workers"])
    maximum_workers = int(args.max_workers or config["maximum_workers"])
    if initial_workers < int(config["minimum_workers"]) or maximum_workers < initial_workers:
        raise SystemExit("worker limits must satisfy minimum_workers <= workers <= max_workers")
    if args.resume and not args.manifest_output and not args.run_id:
        raise SystemExit("--resume requires --run-id or --manifest-output")


def _manifest_path(args: argparse.Namespace, config: dict[str, Any]) -> Path:
    if args.manifest_output is not None:
        return args.manifest_output
    seed = args.sample_seed or str(config["default_sample_seed"])
    run_id = args.run_id or f"free-price-{seed}"
    if not re.fullmatch(r"[A-Za-z0-9._-]+", run_id):
        raise SystemExit("--run-id may contain only letters, digits, dots, underscores, and hyphens")
    return args.cache_dir / "runs" / run_id / "manifest.json"


def _load_or_create_run(args: argparse.Namespace, config: dict[str, Any], manifest_path: Path) -> tuple[dict[str, Any], list[str]]:
    universe_path = manifest_path.parent / "universe.json"
    if args.resume:
        if not manifest_path.exists() or not universe_path.exists():
            raise SystemExit("--resume requires existing manifest.json and universe.json")
        manifest = _read_json(manifest_path)
        universe = _read_json(universe_path)
        symbols = universe.get("symbols")
        if not isinstance(symbols, list) or not all(isinstance(symbol, str) for symbol in symbols):
            raise SystemExit("frozen universe is invalid")
        return manifest, symbols
    if manifest_path.exists() or universe_path.exists():
        raise SystemExit(f"run files already exist at {manifest_path.parent}; use --resume or choose a new --run-id")

    symbols, universe_source = _resolve_symbols(args)
    sample_seed = args.sample_seed or str(config["default_sample_seed"])
    selected = _sample_symbols(symbols, len(symbols) if args.all_symbols else args.max_symbols or int(config["default_max_symbols"]), sample_seed)
    run_id = args.run_id or manifest_path.parent.name
    universe = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": universe_source,
        "candidate_symbol_count": len(symbols),
        "sample_seed": sample_seed,
        "symbols": selected,
    }
    manifest = {
        "run_id": run_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "yfinance_yahoo_adjusted_ohlcv",
        "universe_source": universe_source,
        "requested": {
            "start": args.start.isoformat(),
            "end": args.end.isoformat(),
            "candidate_symbol_count": len(symbols),
            "symbol_count": len(selected),
            "all_symbols": args.all_symbols,
            "sampling": "sha256_seeded",
            "sample_seed": sample_seed,
        },
        "records": {},
        "completed": {},
        "failed": {},
        "batches": [],
        "limitations": [
            "The Nasdaq Trader directory describes current listings only.",
            "This dataset has survivorship bias and must not be used to claim delisted-stock coverage.",
            "Yahoo/yfinance is a free prototype source; inspect coverage and corporate-action behavior before promotion.",
        ],
    }
    _write_json(universe_path, universe)
    _write_json(manifest_path, manifest)
    return manifest, selected


def _download_symbol(symbol: str, args: argparse.Namespace, config: dict[str, Any]) -> dict[str, Any]:
    cached = read_cached_ohlcv(cache_path(args.cache_dir, symbol))
    if _cache_is_recent(cached, args.end, int(config["stale_coverage_days"])) and not args.refresh:
        return _history_record("reused_cache", cached, symbol, args.cache_dir, args.end, attempts=0)
    attempts = int(config["retry_attempts"])
    rate_limited = False
    for attempt in range(1, attempts + 1):
        try:
            history = load_or_fetch_free_adjusted_ohlcv(
                symbol,
                args.start,
                args.end,
                cache_dir=args.cache_dir,
                refresh=args.refresh,
                fetcher=partial(fetch_free_adjusted_ohlcv, timeout_seconds=float(config["request_timeout_seconds"])),
            )
            return _history_record("completed", history, symbol, args.cache_dir, args.end, attempts=attempt)
        except Exception as exc:
            rate_limited = _is_rate_limited(exc) or rate_limited
            if attempt < attempts and _is_retryable(exc):
                time.sleep(float(config["retry_backoff_seconds"]) * 2 ** (attempt - 1))
                continue
            return {"status": "failed", "attempts": attempt, "error": str(exc), "rate_limited": rate_limited}
    raise AssertionError("retry loop must return")


def _history_record(status: str, history: Any, symbol: str, cache_dir: Path, requested_end: date, *, attempts: int) -> dict[str, Any]:
    if history.empty:
        return {"status": "failed", "attempts": attempts, "error": "no adjusted OHLCV returned", "rate_limited": False}
    config = load_free_price_universe_config()["download"]
    latest = history.index.max().date()
    if latest < requested_end - timedelta(days=int(config["stale_coverage_days"])):
        status = "stale"
    elif len(history) < int(config["minimum_history_sessions"]):
        status = "insufficient_history"
    return {
        "status": status,
        "attempts": attempts,
        "rows": len(history),
        "from": history.index.min().date().isoformat(),
        "through": latest.isoformat(),
        "cache_file": cache_path(cache_dir, symbol).name,
        "rate_limited": False,
    }


def _cache_is_recent(history: Any, end: date, stale_days: int) -> bool:
    return not history.empty and history.index.max().date() >= end - timedelta(days=stale_days)


def _is_retryable(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(value in text for value in ("429", "rate limit", "too many", "crumb", "timeout", "temporar", "connection"))


def _is_rate_limited(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(value in text for value in ("429", "rate limit", "too many", "crumb"))


def _records_from_manifest(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    records = manifest.get("records")
    if isinstance(records, dict):
        return {str(symbol): dict(record) for symbol, record in records.items() if isinstance(record, dict)}
    completed = manifest.get("completed", {})
    failed = manifest.get("failed", {})
    records = {
        str(symbol): {"status": "completed", **record}
        for symbol, record in completed.items()
        if isinstance(record, dict)
    }
    records.update(
        {
            str(symbol): {"status": "failed", "error": str(error)}
            for symbol, error in failed.items()
        }
    )
    manifest["records"] = records
    return records


def _refresh_manifest_indexes(manifest: dict[str, Any]) -> None:
    records = _records_from_manifest(manifest)
    manifest["completed"] = {symbol: record for symbol, record in records.items() if record.get("status") in TERMINAL_STATUSES}
    manifest["failed"] = {symbol: record.get("error", "download failed") for symbol, record in records.items() if record.get("status") == "failed"}


class _AdaptiveState:
    def __init__(self, *, workers: int, minimum_workers: int, maximum_workers: int, window_size: int, maximum_failure_rate: float, cooldown_seconds: float) -> None:
        self.workers = workers
        self.minimum_workers = minimum_workers
        self.maximum_workers = maximum_workers
        self.window_size = window_size
        self.maximum_failure_rate = maximum_failure_rate
        self.cooldown_seconds = cooldown_seconds
        self.results: deque[bool] = deque(maxlen=window_size)
        self.cooldown_until = 0.0

    def observe(self, result: dict[str, Any], processed: int) -> None:
        failed = result.get("status") == "failed"
        self.results.append(not failed)
        if result.get("rate_limited"):
            self.workers = max(self.minimum_workers, self.workers - 1)
            self.cooldown_until = time.monotonic() + self.cooldown_seconds
            return
        failure_rate = 1 - sum(self.results) / len(self.results)
        if len(self.results) >= min(20, self.window_size) and failure_rate > self.maximum_failure_rate:
            self.workers = max(self.minimum_workers, self.workers - 1)
        elif len(self.results) == self.window_size and processed % self.window_size == 0 and failure_rate == 0:
            self.workers = min(self.maximum_workers, self.workers + 1)


class _CheckpointWriter:
    def __init__(self, args: argparse.Namespace, config: dict[str, Any], manifest_path: Path, manifest: dict[str, Any]) -> None:
        self.args = args
        self.config = config
        self.manifest_path = manifest_path
        self.manifest = manifest
        self.records: list[tuple[str, dict[str, Any]]] = []
        self.batch_size = int(args.batch_size or config["batch_size"])
        self.client = None
        self.settings = None
        if args.r2_checkpoints:
            load_dotenv(ROOT / ".env")
            self.settings = R2StorageSettings.from_environment()
            self.client = create_r2_client(self.settings)
            self._upload_pending_batches()

    @property
    def ready(self) -> bool:
        return len(self.records) >= self.batch_size

    def add(self, symbol: str, record: dict[str, Any]) -> None:
        self.records.append((symbol, record))

    def flush(self) -> None:
        if not self.records:
            return
        batch_id = len(self.manifest["batches"]) + 1
        batch_path = self.manifest_path.parent / "batches" / f"batch-{batch_id:05d}.json"
        batch = {
            "run_id": self.manifest["run_id"],
            "batch_id": batch_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "completed": {symbol: record for symbol, record in self.records if record.get("status") in TERMINAL_STATUSES},
            "failed": {symbol: record.get("error", "download failed") for symbol, record in self.records if record.get("status") == "failed"},
        }
        _write_json(batch_path, batch)
        batch_meta = {
            "batch_id": batch_id,
            "manifest": str(batch_path),
            "symbol_count": len(self.records),
            "r2_status": "pending" if self.client is not None else "not_requested",
        }
        self.manifest["batches"].append(batch_meta)
        _write_json(self.manifest_path, self.manifest)
        if self.client is not None and self.settings is not None:
            self._upload_batch(batch_meta)
            _write_json(self.manifest_path, self.manifest)
        self.records.clear()

    def upload_final_manifest(self) -> None:
        if self.client is None or self.settings is None:
            return
        upload_verified_plan(
            self.client,
            self.settings.bucket,
            build_upload_plan_for_files(
                [
                    (
                        self.manifest_path,
                        f"manifests/yfinance/us-current-common/{self.manifest['run_id']}/manifest.json",
                    )
                ]
            ),
            storage_limit_bytes=int(self.config["r2_storage_limit_bytes"]),
        )

    def _upload_pending_batches(self) -> None:
        for batch_meta in self.manifest["batches"]:
            if batch_meta.get("r2_status") == "pending":
                self._upload_batch(batch_meta)
        _write_json(self.manifest_path, self.manifest)

    def _upload_batch(self, batch_meta: dict[str, Any]) -> None:
        if self.client is None or self.settings is None:
            return
        batch_path = Path(str(batch_meta["manifest"]))
        batch = _read_json(batch_path)
        files = [
            (cache_path(self.args.cache_dir, symbol), f"raw/yfinance/us-current-common/{self.manifest['run_id']}/prices/{cache_path(self.args.cache_dir, symbol).name}")
            for symbol in batch["completed"]
            if cache_path(self.args.cache_dir, symbol).is_file()
        ]
        files.append((batch_path, f"manifests/yfinance/us-current-common/{self.manifest['run_id']}/batches/{batch_path.name}"))
        upload_verified_plan(
            self.client,
            self.settings.bucket,
            build_upload_plan_for_files(files),
            storage_limit_bytes=int(self.config["r2_storage_limit_bytes"]),
        )
        batch_meta["r2_status"] = "verified"


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False) as temporary_file:
        temporary_path = Path(temporary_file.name)
        temporary_file.write(json.dumps(value, indent=2) + "\n")
    try:
        temporary_path.replace(path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SystemExit(f"expected JSON object in {path}")
    return value


def _resolve_symbols(args: argparse.Namespace) -> tuple[list[str], str]:
    if args.nasdaq_current_common_stocks:
        return fetch_current_us_common_symbols(), "nasdaq_trader_current_common_stocks"
    if args.symbols_file is not None:
        content = args.symbols_file.read_text(encoding="utf-8")
        return _normalize_symbols(re.split(r"[\s,]+", content)), "user_symbols_file"
    return _normalize_symbols(args.symbols.split(",")), "user_symbols"


def _normalize_symbols(values: list[str]) -> list[str]:
    return sorted({value.strip().upper() for value in values if value.strip()})


def _sample_symbols(symbols: list[str], max_symbols: int, sample_seed: str) -> list[str]:
    return sorted(
        _normalize_symbols(symbols),
        key=lambda symbol: hashlib.sha256(f"{sample_seed}:{symbol}".encode("utf-8")).hexdigest(),
    )[:max_symbols]


if __name__ == "__main__":
    raise SystemExit(main())
