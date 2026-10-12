from __future__ import annotations

import json
from pathlib import Path

from backtesting.sec_batch_report import build_sec_batch_progress_report


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _companyfacts_payload(cik: int) -> dict[str, object]:
    return {
        "cik": cik,
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [
                            {"form": "10-Q", "filed": "2024-05-03", "start": "2024-01-01", "end": "2024-03-31", "val": 100, "accn": "rev"}
                        ]
                    }
                },
                "NetIncomeLoss": {
                    "units": {
                        "USD": [
                            {"form": "10-Q", "filed": "2024-05-03", "start": "2024-01-01", "end": "2024-03-31", "val": 20, "accn": "ni"}
                        ]
                    }
                },
                "OperatingIncomeLoss": {
                    "units": {
                        "USD": [
                            {"form": "10-Q", "filed": "2024-05-03", "start": "2024-01-01", "end": "2024-03-31", "val": 15, "accn": "oi"}
                        ]
                    }
                },
                "Assets": {"units": {"USD": [{"form": "10-Q", "filed": "2024-05-03", "end": "2024-03-31", "val": 400, "accn": "assets"}]}},
                "Liabilities": {
                    "units": {"USD": [{"form": "10-Q", "filed": "2024-05-03", "end": "2024-03-31", "val": 150, "accn": "liabilities"}]}
                },
                "StockholdersEquity": {
                    "units": {"USD": [{"form": "10-Q", "filed": "2024-05-03", "end": "2024-03-31", "val": 250, "accn": "equity"}]}
                },
                "EarningsPerShareDiluted": {
                    "units": {
                        "USD/shares": [
                            {"form": "10-Q", "filed": "2024-05-03", "start": "2024-01-01", "end": "2024-03-31", "val": 1.2, "accn": "eps"}
                        ]
                    }
                },
            }
        },
    }


def _write_free_price_fixture(base_dir: Path, *, symbols: list[str]) -> None:
    run_dir = base_dir / "runs" / "fixture"
    _write_json(run_dir / "universe.json", {"symbols": symbols})
    _write_json(
        run_dir / "manifest.json",
        {
            "source": "yfinance_yahoo_adjusted_ohlcv",
            "universe_source": "nasdaq_trader_current_common_stocks",
            "requested": {"start": "2020-01-01", "end": "2024-12-31"},
            "records": {symbol: {"status": "completed", "cache_file": f"{symbol}.csv"} for symbol in symbols},
        },
    )
    for symbol in [*symbols, "SPY", "QQQ", "^VIX"]:
        (base_dir / f"{symbol}.csv").parent.mkdir(parents=True, exist_ok=True)
        (base_dir / f"{symbol}.csv").write_text("date,open,high,low,close,volume\n2024-01-01,1,1,1,1,1\n", encoding="utf-8")


def test_sec_batch_progress_report_summarizes_completed_batch_and_remaining_coverage(tmp_path: Path) -> None:
    free_price_cache_dir = tmp_path / "free_price"
    sec_cache_dir = tmp_path / "sec"
    _write_free_price_fixture(free_price_cache_dir, symbols=["AAA", "BBB", "CCC"])

    _write_json(
        sec_cache_dir / "company_tickers.json",
        {
            "0": {"ticker": "AAA", "cik_str": 320193},
            "1": {"ticker": "BBB", "cik_str": 789019},
            "2": {"ticker": "CCC", "cik_str": 1000010},
        },
    )
    _write_json(sec_cache_dir / "companyfacts" / "0000320193.json", _companyfacts_payload(320193))
    _write_json(sec_cache_dir / "companyfacts" / "0000789019.json", _companyfacts_payload(789019))

    manifest_path = tmp_path / "runs" / "batch-1" / "manifest.json"
    _write_json(
        manifest_path,
        {
            "run_id": "batch-1",
            "source": "sec_edgar_companyfacts",
            "status": "completed",
            "failure_class": "dns",
            "generated_at": "2026-07-19T01:00:00+00:00",
            "completed_at": "2026-07-19T01:05:00+00:00",
            "requested_symbols": ["AAA", "BBB"],
            "completed": {
                "AAA": {"status": "completed", "cik": "0000320193", "cache_file": "companyfacts/0000320193.json"},
                "BBB": {"status": "completed", "cik": "0000789019", "cache_file": "companyfacts/0000789019.json"},
            },
            "failed_symbols": {},
            "missing_companyfacts": {},
            "unmapped_symbols": {},
            "pending_symbols": [],
            "observation_count": 14,
            "next_action": "Use --resume only for a later run_id; this run is complete.",
            "systemic_failure": {"symbol": "AAA", "failure_class": "dns"},
        },
    )

    report = build_sec_batch_progress_report(
        batch_manifest_path=manifest_path,
        free_price_cache_dir=free_price_cache_dir,
        free_price_run_id="fixture",
        sec_cache_dir=sec_cache_dir,
        sample_limit=5,
    )

    assert report["batch_run"]["status"] == "completed"
    assert report["batch_run"]["failure_class"] is None
    assert report["batch_run"]["systemic_failure"] is None
    assert report["batch_run"]["counts"]["requested_symbols"] == 2
    assert report["batch_run"]["counts"]["completed_symbols"] == 2
    assert report["coverage"]["sec_cached_companyfacts_symbols"] == 2
    assert report["coverage"]["sec_uncached_mapped_symbols"] == 1
    assert report["coverage"]["latest_cached_period"]["period"] == "2024-Q1"
    assert report["certification_state"]["forecast_promotion_eligible"] is False
    assert report["artifact_fingerprints"]["batch_manifest_sha256"]
    assert "rebuild the ranked uncached queue" in report["next_action"]


def test_sec_batch_progress_report_preserves_systemic_failure_next_action(tmp_path: Path) -> None:
    free_price_cache_dir = tmp_path / "free_price"
    sec_cache_dir = tmp_path / "sec"
    _write_free_price_fixture(free_price_cache_dir, symbols=["AAA", "BBB"])

    _write_json(
        sec_cache_dir / "company_tickers.json",
        {
            "0": {"ticker": "AAA", "cik_str": 320193},
            "1": {"ticker": "BBB", "cik_str": 789019},
        },
    )
    _write_json(sec_cache_dir / "companyfacts" / "0000320193.json", _companyfacts_payload(320193))

    manifest_path = tmp_path / "runs" / "batch-2" / "manifest.json"
    _write_json(
        manifest_path,
        {
            "run_id": "batch-2",
            "source": "sec_edgar_companyfacts",
            "status": "systemic_failure",
            "failure_class": "dns",
            "generated_at": "2026-07-19T02:00:00+00:00",
            "completed_at": "2026-07-19T02:03:00+00:00",
            "requested_symbols": ["AAA", "BBB"],
            "completed": {
                "AAA": {"status": "completed", "cik": "0000320193", "cache_file": "companyfacts/0000320193.json"}
            },
            "failed_symbols": {"BBB": "ConnectError: nodename nor servname provided, or not known"},
            "missing_companyfacts": {},
            "unmapped_symbols": {},
            "pending_symbols": ["BBB"],
            "systemic_failure": {
                "symbol": "BBB",
                "cik": "0000789019",
                "failure_class": "dns",
                "error": "ConnectError: nodename nor servname provided, or not known",
            },
            "next_action": "Stop the batch, verify DNS/network reachability to sec.gov, then rerun with --resume after a recovery check.",
        },
    )

    report = build_sec_batch_progress_report(
        batch_manifest_path=manifest_path,
        free_price_cache_dir=free_price_cache_dir,
        free_price_run_id="fixture",
        sec_cache_dir=sec_cache_dir,
        sample_limit=5,
    )

    assert report["batch_run"]["status"] == "systemic_failure"
    assert report["batch_run"]["failure_class"] == "dns"
    assert report["batch_run"]["counts"]["failed_symbols"] == 1
    assert report["batch_run"]["counts"]["pending_symbols"] == 1
    assert report["coverage"]["sec_cached_companyfacts_symbols"] == 1
    assert report["coverage"]["sec_uncached_mapped_symbols"] == 1
    assert report["next_action"].startswith("Stop the batch, verify DNS/network reachability")
