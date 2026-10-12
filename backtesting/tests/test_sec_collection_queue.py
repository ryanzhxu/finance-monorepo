from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backtesting.sec_collection_queue import build_sec_collection_queue_report


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_run_manifest(sec_cache_dir: Path, run_id: str, payload: object) -> None:
    _write_json(sec_cache_dir / "runs" / run_id / "manifest.json", payload)


def test_sec_collection_queue_ranks_uncached_symbols_by_price_readiness_and_rows(tmp_path: Path) -> None:
    free_price_cache_dir = tmp_path / "free_price"
    sec_cache_dir = tmp_path / "sec"
    run_dir = free_price_cache_dir / "runs" / "fixture"
    _write_json(run_dir / "universe.json", {"symbols": ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF"]})
    _write_json(
        run_dir / "manifest.json",
        {
            "source": "yfinance_yahoo_adjusted_ohlcv",
            "universe_source": "nasdaq_trader_current_common_stocks",
            "requested": {"start": "2020-01-01", "end": "2024-12-31"},
            "records": {
                "AAA": {"status": "completed", "rows": 500, "from": "2020-01-01", "through": "2024-12-31", "cache_file": "AAA.csv"},
                "BBB": {"status": "reused_cache", "rows": 450, "from": "2020-01-01", "through": "2024-12-31", "cache_file": "BBB.csv"},
                "CCC": {"status": "insufficient_history", "rows": 40, "from": "2024-11-01", "through": "2024-12-31", "cache_file": "CCC.csv"},
                "DDD": {"status": "failed", "rows": 0, "cache_file": "DDD.csv"},
                "EEE": {"status": "completed", "rows": 300, "from": "2020-01-01", "through": "2024-12-31", "cache_file": "EEE.csv"},
            },
        },
    )
    for symbol in ("AAA", "BBB", "CCC", "EEE", "SPY", "QQQ", "^VIX"):
        (free_price_cache_dir / f"{symbol}.csv").write_text("date,open,high,low,close,volume\n2024-01-01,1,1,1,1,1\n", encoding="utf-8")

    _write_json(
        sec_cache_dir / "company_tickers.json",
        {
            "0": {"ticker": "AAA", "cik_str": 320193, "title": "AAA Corp"},
            "1": {"ticker": "BBB", "cik_str": 789019, "title": "BBB Corp"},
            "2": {"ticker": "CCC", "cik_str": 1000010, "title": "CCC Corp"},
            "3": {"ticker": "DDD", "cik_str": 1000011, "title": "DDD Corp"},
            "4": {"ticker": "EEE", "cik_str": 1000012, "title": "EEE Corp"},
        },
    )
    _write_json(sec_cache_dir / "companyfacts" / "0001000012.json", {"cik": 1000012, "facts": {"us-gaap": {}}})

    report = build_sec_collection_queue_report(
        free_price_cache_dir=free_price_cache_dir,
        free_price_run_id="fixture",
        sec_cache_dir=sec_cache_dir,
        batch_size=3,
    )

    assert report["coverage_context"]["sec_uncached_mapped_symbols"] == 4
    assert report["queue_summary"]["requested_symbol_count"] == 4
    assert report["queue_summary"]["candidate_batch_size"] == 3
    assert report["queue_summary"]["deferred_symbol_count"] == 1
    assert report["queue_summary"]["priority_bucket_counts"]["ready_price_history"] == 2
    assert report["queue_summary"]["price_status_counts"]["completed"] == 1
    assert report["queue_summary"]["price_status_counts"]["reused_cache"] == 1
    assert report["candidate_batch_symbols"] == ["AAA", "BBB", "CCC"]
    assert [entry["symbol"] for entry in report["ranked_uncached_symbols"]] == ["AAA", "BBB", "CCC", "DDD"]
    assert report["batch_execution_gate"]["eligible_for_new_batch"] is True
    assert report["batch_execution_gate"]["calendar_day_started_run_count"] == 0
    assert report["ranked_uncached_symbols"][0]["rank"] == 1
    assert report["ranked_uncached_symbols"][0]["priority_bucket"] == "ready_price_history"
    assert report["ranked_uncached_symbols"][3]["priority_bucket"] == "price_fetch_failed"
    assert report["ranked_uncached_symbols"][3]["price_status"] == "failed"
    assert "candidate_batch_symbols" in report["next_action"]


def test_sec_collection_queue_treats_shared_cik_cache_as_already_resolved(tmp_path: Path) -> None:
    free_price_cache_dir = tmp_path / "free_price"
    sec_cache_dir = tmp_path / "sec"
    run_dir = free_price_cache_dir / "runs" / "fixture"
    _write_json(run_dir / "universe.json", {"symbols": ["AAA", "AAA-PRA"]})
    _write_json(
        run_dir / "manifest.json",
        {
            "source": "yfinance_yahoo_adjusted_ohlcv",
            "universe_source": "nasdaq_trader_current_common_stocks",
            "requested": {"start": "2020-01-01", "end": "2024-12-31"},
            "records": {
                "AAA": {"status": "completed", "rows": 500, "cache_file": "AAA.csv"},
                "AAA-PRA": {"status": "completed", "rows": 450, "cache_file": "AAA-PRA.csv"},
            },
        },
    )
    for symbol in ("AAA", "AAA-PRA", "SPY", "QQQ", "^VIX"):
        (free_price_cache_dir / f"{symbol}.csv").write_text("date,open,high,low,close,volume\n2024-01-01,1,1,1,1,1\n", encoding="utf-8")

    _write_json(
        sec_cache_dir / "company_tickers.json",
        {
            "0": {"ticker": "AAA", "cik_str": 320193, "title": "AAA Corp"},
            "1": {"ticker": "AAA-PRA", "cik_str": 320193, "title": "AAA Preferred"},
        },
    )
    _write_json(sec_cache_dir / "companyfacts" / "0000320193.json", {"cik": 320193, "facts": {"us-gaap": {}}})

    report = build_sec_collection_queue_report(
        free_price_cache_dir=free_price_cache_dir,
        free_price_run_id="fixture",
        sec_cache_dir=sec_cache_dir,
        batch_size=10,
    )

    assert report["coverage_context"]["sec_cached_companyfacts_symbols"] == 2
    assert report["coverage_context"]["sec_uncached_mapped_symbols"] == 0
    assert report["candidate_batch_symbols"] == []
    assert report["ranked_uncached_symbols"] == []


def test_sec_collection_queue_blocks_new_batch_for_unresolved_systemic_failure_run(tmp_path: Path) -> None:
    free_price_cache_dir = tmp_path / "free_price"
    sec_cache_dir = tmp_path / "sec"
    run_dir = free_price_cache_dir / "runs" / "fixture"
    _write_json(run_dir / "universe.json", {"symbols": ["AAA"]})
    _write_json(
        run_dir / "manifest.json",
        {
            "source": "yfinance_yahoo_adjusted_ohlcv",
            "universe_source": "nasdaq_trader_current_common_stocks",
            "requested": {"start": "2020-01-01", "end": "2024-12-31"},
            "records": {"AAA": {"status": "completed", "rows": 500, "cache_file": "AAA.csv"}},
        },
    )
    for symbol in ("AAA", "SPY", "QQQ", "^VIX"):
        (free_price_cache_dir / f"{symbol}.csv").write_text("date,open,high,low,close,volume\n2024-01-01,1,1,1,1,1\n", encoding="utf-8")
    _write_json(sec_cache_dir / "company_tickers.json", {"0": {"ticker": "AAA", "cik_str": 320193, "title": "AAA Corp"}})
    _write_run_manifest(
        sec_cache_dir,
        "stock-28-sec-batch-active",
        {
            "run_id": "stock-28-sec-batch-active",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "status": "systemic_failure",
            "requested_symbols": ["AAA"],
            "pending_symbols": ["AAA"],
            "failure_class": "dns",
        },
    )

    report = build_sec_collection_queue_report(
        free_price_cache_dir=free_price_cache_dir,
        free_price_run_id="fixture",
        sec_cache_dir=sec_cache_dir,
        batch_size=10,
    )

    assert report["batch_execution_gate"]["eligible_for_new_batch"] is False
    assert report["batch_execution_gate"]["blocking_run_ids"] == ["stock-28-sec-batch-active"]
    assert "systemic_failure" in str(report["batch_execution_gate"]["blocking_reason"])
    assert report["run_history"][0]["run_id"] == "stock-28-sec-batch-active"
    assert report["next_action"].startswith("Do not start a new SEC batch.")


def test_sec_collection_queue_blocks_new_batch_after_four_same_day_starts(tmp_path: Path) -> None:
    free_price_cache_dir = tmp_path / "free_price"
    sec_cache_dir = tmp_path / "sec"
    run_dir = free_price_cache_dir / "runs" / "fixture"
    _write_json(run_dir / "universe.json", {"symbols": ["AAA"]})
    _write_json(
        run_dir / "manifest.json",
        {
            "source": "yfinance_yahoo_adjusted_ohlcv",
            "universe_source": "nasdaq_trader_current_common_stocks",
            "requested": {"start": "2020-01-01", "end": "2024-12-31"},
            "records": {"AAA": {"status": "completed", "rows": 500, "cache_file": "AAA.csv"}},
        },
    )
    for symbol in ("AAA", "SPY", "QQQ", "^VIX"):
        (free_price_cache_dir / f"{symbol}.csv").write_text("date,open,high,low,close,volume\n2024-01-01,1,1,1,1,1\n", encoding="utf-8")
    _write_json(sec_cache_dir / "company_tickers.json", {"0": {"ticker": "AAA", "cik_str": 320193, "title": "AAA Corp"}})

    base_time = datetime.now(timezone.utc).replace(hour=1, minute=0, second=0, microsecond=0)
    for index in range(4):
        _write_run_manifest(
            sec_cache_dir,
            f"stock-28-sec-batch-{index + 1}",
            {
                "run_id": f"stock-28-sec-batch-{index + 1}",
                "generated_at": (base_time + timedelta(hours=index)).isoformat(),
                "completed_at": (base_time + timedelta(hours=index, minutes=10)).isoformat(),
                "status": "completed",
                "requested_symbols": ["AAA"],
                "pending_symbols": [],
                "failure_class": None,
            },
        )

    report = build_sec_collection_queue_report(
        free_price_cache_dir=free_price_cache_dir,
        free_price_run_id="fixture",
        sec_cache_dir=sec_cache_dir,
        batch_size=10,
    )

    assert report["batch_execution_gate"]["eligible_for_new_batch"] is False
    assert report["batch_execution_gate"]["calendar_day_started_run_count"] == 4
    assert len(report["batch_execution_gate"]["calendar_day_started_run_ids"]) == 4
    assert "do not exceed the cap of 4" in str(report["batch_execution_gate"]["blocking_reason"])
    assert report["next_action"].startswith("Do not start a new SEC batch.")
