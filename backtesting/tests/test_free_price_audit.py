from __future__ import annotations

import json
from pathlib import Path

from backtesting.free_price_audit import audit_free_price_run


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_cache_audit_fingerprints_referenced_files_and_preserves_fail_closed_provenance(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    _write_json(
        cache_dir / "runs" / "fixture" / "universe.json",
        {"symbols": ["AAA", "BBB"]},
    )
    _write_json(
        cache_dir / "runs" / "fixture" / "manifest.json",
        {
            "source": "yfinance_yahoo_adjusted_ohlcv",
            "universe_source": "nasdaq_trader_current_common_stocks",
            "requested": {"start": "2020-01-01", "end": "2024-12-31"},
            "records": {
                "AAA": {"status": "completed", "cache_file": "AAA.csv"},
                "BBB": {"status": "failed"},
            },
            "limitations": ["current universe"],
        },
    )
    (cache_dir / "AAA.csv").write_text("date,close\n2020-01-01,1\n", encoding="utf-8")
    for name in ("SPY.csv", "QQQ.csv", "_VIX.csv"):
        (cache_dir / name).write_text("date,close\n2020-01-01,1\n", encoding="utf-8")

    report = audit_free_price_run(cache_dir, "fixture")

    assert report["source_provenance"]["point_in_time_certified"] is False
    assert report["symbol_counts"] == {"universe": 2, "records": 2, "missing_records": 0, "unknown_records": 0}
    assert report["cache_files"]["referenced_file_count"] == 1
    assert report["cache_files"]["missing_files"] == []
    assert report["benchmarks"]["available_count"] == 3
    assert report["reproducible_cache_only"] is True
    assert len(report["cache_fingerprint_sha256"]) == 64


def test_cache_audit_rejects_missing_record_and_reports_missing_referenced_file(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    _write_json(cache_dir / "runs" / "fixture" / "universe.json", {"symbols": ["AAA", "BBB"]})
    _write_json(
        cache_dir / "runs" / "fixture" / "manifest.json",
        {"records": {"AAA": {"status": "completed", "cache_file": "AAA.csv"}}},
    )

    report = audit_free_price_run(cache_dir, "fixture")

    assert report["symbol_counts"]["missing_records"] == 1
    assert report["cache_files"]["missing_files"] == ["AAA"]
    assert report["reproducible_cache_only"] is False
