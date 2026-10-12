from __future__ import annotations

import json
from pathlib import Path

from backtesting.sec_edgar_audit import audit_sec_edgar_cache


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _companyfacts_payload(cik: int, *, missing_eps: bool) -> dict[str, object]:
    facts = {
        "Revenues": {
            "units": {"USD": [{"form": "10-Q", "filed": "2024-05-03", "start": "2024-01-01", "end": "2024-03-31", "val": 100, "accn": "rev"}]}
        },
        "NetIncomeLoss": {
            "units": {"USD": [{"form": "10-Q", "filed": "2024-05-03", "start": "2024-01-01", "end": "2024-03-31", "val": 20, "accn": "ni"}]}
        },
        "OperatingIncomeLoss": {
            "units": {"USD": [{"form": "10-Q", "filed": "2024-05-03", "start": "2024-01-01", "end": "2024-03-31", "val": 25, "accn": "oi"}]}
        },
        "Assets": {
            "units": {"USD": [{"form": "10-Q", "filed": "2024-05-03", "end": "2024-03-31", "val": 400, "accn": "assets"}]}
        },
        "StockholdersEquity": {
            "units": {"USD": [{"form": "10-Q", "filed": "2024-05-03", "end": "2024-03-31", "val": 150, "accn": "equity"}]}
        },
    }
    if not missing_eps:
        facts["EarningsPerShareDiluted"] = {
            "units": {"USD/shares": [{"form": "10-Q", "filed": "2024-05-03", "start": "2024-01-01", "end": "2024-03-31", "val": 1.2, "accn": "eps"}]}
        }
    return {"cik": cik, "facts": {"us-gaap": facts}}


def test_sec_cache_audit_reports_universe_coverage_and_period_missingness(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    _write_json(
        cache_dir / "company_tickers.json",
        {
            "0": {"ticker": "AAA", "cik_str": 320193},
            "1": {"ticker": "BBB", "cik_str": 789019},
        },
    )
    _write_json(cache_dir / "companyfacts" / "0000320193.json", _companyfacts_payload(320193, missing_eps=True))
    universe_path = tmp_path / "universe.json"
    _write_json(universe_path, {"source": "fixture", "symbols": ["AAA", "BBB"]})

    report = audit_sec_edgar_cache(cache_dir, universe_path=universe_path)

    assert report["cache_inventory"]["companyfacts_file_count"] == 1
    assert report["universe_reference"]["mapped_to_sec"] == 2
    assert report["universe_reference"]["cached_companyfacts"] == 1
    assert report["universe_reference"]["uncached_companyfacts"] == 1
    assert report["recent_period_coverage"][0]["period"] == "2024-Q1"
    assert report["recent_period_coverage"][0]["missing_feature_counts"]["eps"] == 1
    assert report["symbol_period_coverage"]["missing_feature_counts"]["eps"] == 1
    assert report["sample_symbol_period_gaps"][0]["symbol"] == "AAA"
    assert report["sample_symbol_period_gaps"][0]["latest_gap_missing_features"] == ["eps"]


def test_sec_cache_audit_counts_complete_feature_periods(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    _write_json(
        cache_dir / "company_tickers.json",
        {
            "0": {"ticker": "AAA", "cik_str": 320193},
        },
    )
    _write_json(cache_dir / "companyfacts" / "0000320193.json", _companyfacts_payload(320193, missing_eps=False))

    report = audit_sec_edgar_cache(cache_dir)

    assert report["symbol_period_coverage"]["symbol_count"] == 1
    assert report["symbol_period_coverage"]["complete_feature_input_periods"] == 1
    assert report["recent_period_coverage"][0]["complete_feature_input_symbols"] == 1
    assert report["sample_symbol_period_gaps"] == []


def test_sec_cache_audit_counts_shared_cik_symbols_as_cached(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    _write_json(
        cache_dir / "company_tickers.json",
        {
            "0": {"ticker": "AAA", "cik_str": 320193},
            "1": {"ticker": "AAA-PRA", "cik_str": 320193},
            "2": {"ticker": "BBB", "cik_str": 789019},
        },
    )
    _write_json(cache_dir / "companyfacts" / "0000320193.json", _companyfacts_payload(320193, missing_eps=False))
    universe_path = tmp_path / "universe.json"
    _write_json(universe_path, {"source": "fixture", "symbols": ["AAA", "AAA-PRA", "BBB"]})

    report = audit_sec_edgar_cache(cache_dir, universe_path=universe_path)

    assert report["cache_inventory"]["companyfacts_file_count"] == 1
    assert report["universe_reference"]["mapped_to_sec"] == 3
    assert report["universe_reference"]["cached_companyfacts"] == 2
    assert report["universe_reference"]["uncached_companyfacts"] == 1
    assert report["universe_reference"]["sample_uncached_symbols"] == ["BBB"]
