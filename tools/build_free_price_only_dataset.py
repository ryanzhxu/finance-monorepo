from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtesting.forecast_dataset import build_forecast_observations
from backtesting.free_price_cache import cache_path, read_cached_ohlcv
from backtesting.free_price_dataset import build_price_only_snapshots, fetch_free_adjusted_ohlcv
from backtesting.entry_timing import evaluate_entry_timing
from backtesting.forecast_features import (
    CONTINUOUS_FEATURE_SCHEMA,
    MarketFeatureProvider,
    attach_continuous_features,
    load_forecast_feature_config,
)
from backtesting.forecast_provenance import build_yfinance_price_provenance


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a free, price-only point-in-time forecast dataset")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--symbols", help="Comma-separated symbols")
    source.add_argument("--symbols-file", type=Path, help="One symbol per line or comma-separated symbols")
    source.add_argument("--manifest", type=Path, help="Manifest produced by download_free_price_history.py")
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--snapshots-output", type=Path, required=True)
    parser.add_argument("--observations-output", type=Path, required=True)
    parser.add_argument("--provenance-output", type=Path, required=True)
    parser.add_argument("--entry-outcomes-output", type=Path)
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--benchmark-cache-dir", type=Path, help="Cache directory containing SPY, QQQ, and ^VIX")
    parser.add_argument(
        "--feature-schema",
        choices=["bucket_v1", CONTINUOUS_FEATURE_SCHEMA],
        default="bucket_v1",
        help="Feature payload attached to each executable-label observation",
    )
    parser.add_argument("--max-symbols", type=int)
    parser.add_argument("--workers", type=int, default=1, help="Cache-only symbol workers; output remains deterministic")
    parser.add_argument(
        "--snapshot-step-sessions",
        type=int,
        default=1,
        help="Keep every Nth eligible as-of session; use the forecast horizon to avoid overlapping labels",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source_text = _source_text(args)
    symbols = sorted({symbol.strip().upper() for symbol in source_text.replace("\n", ",").split(",") if symbol.strip()})
    if not symbols:
        raise SystemExit("--symbols must contain at least one symbol")
    if args.max_symbols is not None:
        if args.max_symbols <= 0:
            raise SystemExit("--max-symbols must be positive")
        symbols = symbols[: args.max_symbols]
    if args.workers <= 0:
        raise SystemExit("--workers must be positive")
    if args.snapshot_step_sessions <= 0:
        raise SystemExit("--snapshot-step-sessions must be positive")

    market_features = _load_market_features(args)
    result_iterator = _symbol_results(symbols, args, market_features=market_features)
    snapshot_count, observation_count, entry_outcome_count, skipped = _write_results(args, result_iterator)
    provenance = build_yfinance_price_provenance(
        requested_start=args.start,
        requested_end=args.end,
        symbols_requested=len(symbols),
        symbols_with_observations=_symbols_with_observations(args.observations_output),
        run_id=_run_id(args.manifest),
        snapshot_step_sessions=args.snapshot_step_sessions,
        feature_schema_version=args.feature_schema,
        benchmark_symbols=_benchmark_symbols(args.feature_schema),
    )
    args.provenance_output.parent.mkdir(parents=True, exist_ok=True)
    args.provenance_output.write_text(provenance.model_dump_json(indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "source": "yfinance_price_only",
                "symbols_requested_count": len(symbols),
                "snapshot_count": snapshot_count,
                "observation_count": observation_count,
                "entry_outcome_count": entry_outcome_count,
                "skipped": skipped,
                "provenance": provenance.model_dump(mode="json"),
            },
            indent=2,
        )
    )
    return 0


def _symbol_results(symbols: list[str], args: argparse.Namespace, *, market_features: MarketFeatureProvider | None = None):
    if args.workers == 1:
        return map(lambda symbol: _build_symbol_result(symbol, args, market_features=market_features), symbols)
    executor = ThreadPoolExecutor(max_workers=args.workers)
    return _ExecutorResultIterator(
        executor,
        executor.map(lambda symbol: _build_symbol_result(symbol, args, market_features=market_features), symbols),
    )


def _build_symbol_result(symbol: str, args: argparse.Namespace, *, market_features: MarketFeatureProvider | None = None):
    requested_start = args.start - timedelta(days=400)
    requested_end = args.end + timedelta(days=140)
    history = (
        _cached_history(args.cache_dir, symbol, requested_start, requested_end)
        if args.cache_dir is not None
        else fetch_free_adjusted_ohlcv(symbol, requested_start, requested_end)
    )
    snapshots = [
        snapshot
        for snapshot in build_price_only_snapshots(symbol, history.loc[: pd.Timestamp(args.end)])
        if snapshot.as_of.date() >= args.start
    ]
    snapshots = snapshots[:: getattr(args, "snapshot_step_sessions", 1)]
    observations, skipped = build_forecast_observations(snapshots, price_loader=lambda _symbol, _start, _end: history)
    if getattr(args, "feature_schema", "bucket_v1") == CONTINUOUS_FEATURE_SCHEMA:
        if market_features is None:
            raise RuntimeError("continuous_regime_v1 requires cached benchmark histories")
        observations, feature_skipped = attach_continuous_features(observations, history, market_features)
        for key, value in feature_skipped.items():
            skipped[key] = skipped.get(key, 0) + value
    outcomes = (
        [
            outcome
            for snapshot in snapshots
            for outcome in evaluate_entry_timing(symbol, snapshot.as_of.date(), history, horizon_sessions=63)
        ]
        if args.entry_outcomes_output is not None
        else []
    )
    return snapshots, observations, outcomes, skipped


def _load_market_features(args: argparse.Namespace) -> MarketFeatureProvider | None:
    if getattr(args, "feature_schema", "bucket_v1") != CONTINUOUS_FEATURE_SCHEMA:
        return None
    cache_dir = args.benchmark_cache_dir or args.cache_dir
    if cache_dir is None:
        raise SystemExit("continuous_regime_v1 requires --cache-dir or --benchmark-cache-dir")
    config = load_forecast_feature_config()
    histories = {
        str(symbol): read_cached_ohlcv(cache_path(cache_dir, str(symbol)))
        for symbol in config["benchmark_symbols"].values()
    }
    missing = [symbol for symbol, history in histories.items() if history.empty]
    if missing:
        raise SystemExit(f"missing benchmark cache histories: {', '.join(sorted(missing))}")
    return MarketFeatureProvider(histories, config=config)


def _benchmark_symbols(feature_schema: str) -> list[str]:
    if feature_schema != CONTINUOUS_FEATURE_SCHEMA:
        return []
    return sorted(str(symbol) for symbol in load_forecast_feature_config()["benchmark_symbols"].values())


class _ExecutorResultIterator:
    def __init__(self, executor: ThreadPoolExecutor, results: Iterable[object]) -> None:
        self.executor = executor
        self.results = results

    def __iter__(self):
        try:
            yield from self.results
        finally:
            self.executor.shutdown(wait=True)


def _write_results(args: argparse.Namespace, results: Iterable[object]) -> tuple[int, int, int, dict[str, int]]:
    snapshots_count = observations_count = outcomes_count = 0
    skipped: dict[str, int] = {}
    with ExitStack() as stack:
        snapshot_handle = _open_output(stack, args.snapshots_output)
        observation_handle = _open_output(stack, args.observations_output)
        outcome_handle = _open_output(stack, args.entry_outcomes_output) if args.entry_outcomes_output is not None else None
        for snapshots, observations, outcomes, symbol_skipped in results:
            for snapshot in snapshots:
                snapshot_handle.write(json.dumps(snapshot.model_dump(mode="json")) + "\n")
                snapshots_count += 1
            for observation in observations:
                observation_handle.write(json.dumps(observation.model_dump(mode="json")) + "\n")
                observations_count += 1
            if outcome_handle is not None:
                for outcome in outcomes:
                    outcome_handle.write(json.dumps(outcome.model_dump(mode="json")) + "\n")
                    outcomes_count += 1
            for key, value in symbol_skipped.items():
                skipped[key] = skipped.get(key, 0) + value
    return snapshots_count, observations_count, outcomes_count, skipped


def _source_text(args: argparse.Namespace) -> str:
    if args.symbols is not None:
        return args.symbols
    if args.symbols_file is not None:
        return args.symbols_file.read_text(encoding="utf-8")
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    completed = manifest.get("completed", {})
    if not isinstance(completed, dict):
        raise SystemExit("manifest completed field must be an object")
    return ",".join(completed)


def _run_id(manifest_path: Path | None) -> str | None:
    if manifest_path is None:
        return None
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    run_id = manifest.get("run_id")
    return run_id if isinstance(run_id, str) and run_id else None


def _symbols_with_observations(path: Path) -> int:
    symbols: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            value = json.loads(line).get("symbol")
            if isinstance(value, str):
                symbols.add(value)
    return len(symbols)


def _cached_history(cache_dir: Path, symbol: str, start: date, end: date) -> pd.DataFrame:
    history = read_cached_ohlcv(cache_path(cache_dir, symbol))
    return history if history.empty else history.loc[pd.Timestamp(start) : pd.Timestamp(end)]


def _open_output(stack: ExitStack, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    return stack.enter_context(path.open("w", encoding="utf-8"))


if __name__ == "__main__":
    raise SystemExit(main())
