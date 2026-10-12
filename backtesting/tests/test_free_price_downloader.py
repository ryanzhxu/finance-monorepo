import argparse
from datetime import date
from pathlib import Path

import pandas as pd

from tools import download_free_price_history as downloader


def _args(tmp_path: Path, *, resume: bool = False) -> argparse.Namespace:
    return argparse.Namespace(
        all_symbols=True,
        max_symbols=None,
        sample_seed="run-seed",
        start=date(2020, 1, 1),
        end=date(2024, 12, 31),
        run_id="run-1",
        manifest_output=None,
        cache_dir=tmp_path / "cache",
        resume=resume,
        refresh=False,
        r2_checkpoints=False,
        batch_size=None,
    )


def _config() -> dict[str, object]:
    return {
        "default_sample_seed": "free-price-v1",
        "default_max_symbols": 500,
        "minimum_workers": 3,
        "initial_workers": 6,
        "maximum_workers": 12,
        "batch_size": 2,
        "stale_coverage_days": 7,
        "minimum_history_sessions": 200,
        "request_timeout_seconds": 30,
        "retry_attempts": 1,
        "retry_backoff_seconds": 0,
    }


def test_run_freezes_universe_and_resume_does_not_refetch_current_listing(tmp_path: Path, monkeypatch) -> None:
    args = _args(tmp_path)
    monkeypatch.setattr(downloader, "_resolve_symbols", lambda _: (["AAPL", "MSFT", "NVDA"], "fake"))
    manifest_path = downloader._manifest_path(args, _config())

    created, symbols = downloader._load_or_create_run(args, _config(), manifest_path)

    assert created["requested"]["symbol_count"] == 3
    assert symbols == downloader._sample_symbols(["AAPL", "MSFT", "NVDA"], 3, "run-seed")
    monkeypatch.setattr(downloader, "_resolve_symbols", lambda _: (_ for _ in ()).throw(AssertionError("must not fetch")))
    resumed, resumed_symbols = downloader._load_or_create_run(_args(tmp_path, resume=True), _config(), manifest_path)

    assert resumed["run_id"] == "run-1"
    assert resumed_symbols == symbols


def test_historical_run_is_not_marked_stale_against_today(monkeypatch, tmp_path: Path) -> None:
    index = pd.date_range("2024-03-01", periods=220, freq="B")
    history = pd.DataFrame(
        {"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0},
        index=index,
    )
    monkeypatch.setattr(downloader, "load_free_price_universe_config", lambda: {"download": _config()})

    record = downloader._history_record("completed", history, "TEST", tmp_path, date(2024, 12, 31), attempts=1)

    assert record["status"] == "completed"


def test_adaptive_workers_increase_after_clean_window_and_reduce_for_rate_limit(monkeypatch) -> None:
    clock = iter([10.0])
    monkeypatch.setattr(downloader.time, "monotonic", lambda: next(clock))
    state = downloader._AdaptiveState(
        workers=6,
        minimum_workers=3,
        maximum_workers=12,
        window_size=3,
        maximum_failure_rate=0.05,
        cooldown_seconds=60,
    )

    for processed in range(1, 4):
        state.observe({"status": "completed", "rate_limited": False}, processed)
    assert state.workers == 7

    state.observe({"status": "failed", "rate_limited": True}, 4)
    assert state.workers == 6
    assert state.cooldown_until == 70.0


def test_checkpoint_writes_completed_and_failed_batch(tmp_path: Path) -> None:
    args = _args(tmp_path)
    manifest = {"run_id": "run-1", "batches": []}
    writer = downloader._CheckpointWriter(args, _config(), tmp_path / "manifest.json", manifest)
    writer.add("AAPL", {"status": "completed", "cache_file": "AAPL.csv"})
    writer.add("BAD", {"status": "failed", "error": "no data"})

    writer.flush()

    batch = downloader._read_json(tmp_path / "batches" / "batch-00001.json")
    assert set(batch["completed"]) == {"AAPL"}
    assert batch["failed"] == {"BAD": "no data"}
    assert manifest["batches"][0]["r2_status"] == "not_requested"


def test_downloader_passes_configured_timeout_to_yfinance_fetcher(monkeypatch, tmp_path: Path) -> None:
    args = _args(tmp_path)
    captured: dict[str, object] = {}
    history = pd.DataFrame(
        {"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0},
        index=pd.date_range("2024-01-01", periods=220, freq="B"),
    )
    config = _config()
    config["request_timeout_seconds"] = 12

    monkeypatch.setattr(downloader, "read_cached_ohlcv", lambda _: pd.DataFrame())

    def fake_loader(*_args: object, **kwargs: object) -> pd.DataFrame:
        fetcher = kwargs["fetcher"]
        captured.update(fetcher.keywords)
        return history

    monkeypatch.setattr(downloader, "load_or_fetch_free_adjusted_ohlcv", fake_loader)

    result = downloader._download_symbol("TEST", args, config)

    assert result["status"] in {"completed", "stale"}
    assert captured == {"timeout_seconds": 12.0}
