import argparse
from datetime import date
from pathlib import Path

import pandas as pd

from backtesting.free_price_cache import cache_path, write_cached_ohlcv
from backtesting.forecast_features import CONTINUOUS_FEATURE_SCHEMA, MarketFeatureProvider
from tools import build_free_price_only_dataset as builder


def _history() -> pd.DataFrame:
    index = pd.date_range("2020-01-01", periods=340, freq="B")
    close = pd.Series(range(100, 440), index=index, dtype=float)
    return pd.DataFrame({"open": close, "high": close + 1, "low": close - 1, "close": close, "volume": 100}, index=index)


def _args(tmp_path: Path, workers: int) -> argparse.Namespace:
    return argparse.Namespace(
        start=date(2020, 9, 1),
        end=date(2021, 2, 1),
        cache_dir=tmp_path / "cache",
        entry_outcomes_output=None,
        workers=workers,
        snapshot_step_sessions=1,
        snapshots_output=tmp_path / f"snapshots-{workers}.jsonl",
        observations_output=tmp_path / f"observations-{workers}.jsonl",
    )


def test_parallel_builder_preserves_deterministic_symbol_order(tmp_path: Path) -> None:
    for symbol in ("BBB", "AAA"):
        write_cached_ohlcv(cache_path(tmp_path / "cache", symbol), _history())

    one_worker = _args(tmp_path, workers=1)
    two_workers = _args(tmp_path, workers=2)
    builder._write_results(one_worker, builder._symbol_results(["AAA", "BBB"], one_worker))
    builder._write_results(two_workers, builder._symbol_results(["AAA", "BBB"], two_workers))

    assert one_worker.snapshots_output.read_text(encoding="utf-8") == two_workers.snapshots_output.read_text(encoding="utf-8")
    assert one_worker.observations_output.read_text(encoding="utf-8") == two_workers.observations_output.read_text(encoding="utf-8")


def test_builder_samples_non_overlapping_forecast_sessions(tmp_path: Path) -> None:
    write_cached_ohlcv(cache_path(tmp_path / "cache", "AAA"), _history())
    args = _args(tmp_path, workers=1)
    args.snapshot_step_sessions = 63

    snapshots, observations, _outcomes, _skipped = builder._build_symbol_result("AAA", args)

    assert len(snapshots) >= 2
    assert observations
    assert (snapshots[1].as_of.date() - snapshots[0].as_of.date()).days >= 63


def test_builder_attaches_continuous_features_from_cached_benchmarks(tmp_path: Path) -> None:
    history = _history()
    for symbol in ("AAA", "SPY", "QQQ", "^VIX"):
        write_cached_ohlcv(cache_path(tmp_path / "cache", symbol), history)
    args = _args(tmp_path, workers=1)
    args.feature_schema = CONTINUOUS_FEATURE_SCHEMA
    provider = MarketFeatureProvider({symbol: history for symbol in ("SPY", "QQQ", "^VIX")})

    _snapshots, observations, _outcomes, skipped = builder._build_symbol_result("AAA", args, market_features=provider)

    assert observations
    assert "missing_continuous_features" not in skipped
    assert observations[0].feature_schema_version == CONTINUOUS_FEATURE_SCHEMA
    assert observations[0].feature_values["relative_strength_63d"] == 0
