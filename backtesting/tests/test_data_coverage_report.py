from __future__ import annotations

import json
from pathlib import Path

from backtesting.data_coverage_report import build_stock_coverage_bias_report


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


def test_stock_coverage_bias_report_separates_uncached_and_true_feature_gaps(tmp_path: Path) -> None:
    free_price_cache_dir = tmp_path / "free_price"
    sec_cache_dir = tmp_path / "sec"
    run_dir = free_price_cache_dir / "runs" / "fixture"
    _write_json(run_dir / "universe.json", {"symbols": ["AAA", "BBB", "CCC"]})
    _write_json(
        run_dir / "manifest.json",
        {
            "source": "yfinance_yahoo_adjusted_ohlcv",
            "universe_source": "nasdaq_trader_current_common_stocks",
            "requested": {"start": "2020-01-01", "end": "2024-12-31"},
            "records": {
                "AAA": {"status": "completed", "cache_file": "AAA.csv"},
                "BBB": {"status": "completed", "cache_file": "BBB.csv"},
                "CCC": {"status": "completed", "cache_file": "CCC.csv"},
            },
            "limitations": ["current listings universe only"],
        },
    )
    for symbol in ("AAA", "BBB", "CCC", "SPY", "QQQ", "_VIX"):
        (free_price_cache_dir / f"{symbol}.csv").write_text("date,open,high,low,close,volume\n2024-01-01,1,1,1,1,1\n", encoding="utf-8")

    _write_json(
        sec_cache_dir / "company_tickers.json",
        {
            "0": {"ticker": "AAA", "cik_str": 320193},
            "1": {"ticker": "BBB", "cik_str": 789019},
        },
    )
    _write_json(sec_cache_dir / "companyfacts" / "0000320193.json", _companyfacts_payload(320193, missing_eps=True))

    report = build_stock_coverage_bias_report(
        free_price_cache_dir=free_price_cache_dir,
        free_price_run_id="fixture",
        sec_cache_dir=sec_cache_dir,
        sample_limit=5,
    )

    assert report["coverage_split"]["price_universe_symbols"] == 3
    assert report["coverage_split"]["sec_cached_companyfacts_symbols"] == 1
    assert report["coverage_split"]["sec_uncached_mapped_symbols"] == 1
    assert report["coverage_split"]["sec_unmapped_universe_symbols"] == 1
    assert report["filing_gap_analysis"]["latest_period"]["period"] == "2024-Q1"
    assert report["filing_gap_analysis"]["latest_period"]["symbols_with_missing_features"] == 1
    assert report["filing_gap_analysis"]["sample_symbols_with_feature_gaps"][0]["symbol"] == "AAA"
    assert report["bias_summary"]["unresolved_coverage_gaps_are_separate_from_feature_gaps"] is True
    assert report["certification_state"]["forecast_promotion_eligible"] is False
    assert "uncached mapped symbols" in report["next_action"]


def test_stock_coverage_bias_report_handles_missing_recent_sec_periods(tmp_path: Path) -> None:
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
            "records": {"AAA": {"status": "completed", "cache_file": "AAA.csv"}},
        },
    )
    for symbol in ("AAA", "SPY", "QQQ", "_VIX"):
        (free_price_cache_dir / f"{symbol}.csv").write_text("date,open,high,low,close,volume\n2024-01-01,1,1,1,1,1\n", encoding="utf-8")

    _write_json(sec_cache_dir / "company_tickers.json", {"0": {"ticker": "AAA", "cik_str": 320193}})
    _write_json(sec_cache_dir / "companyfacts" / "0000320193.json", {"cik": 320193, "facts": {"us-gaap": {}}})

    report = build_stock_coverage_bias_report(
        free_price_cache_dir=free_price_cache_dir,
        free_price_run_id="fixture",
        sec_cache_dir=sec_cache_dir,
        sample_limit=5,
    )

    assert report["filing_gap_analysis"]["latest_period"]["period"] is None
    assert report["filing_gap_analysis"]["latest_period"]["symbols_with_missing_features"] == 0
    assert report["filing_gap_analysis"]["sample_symbols_with_feature_gaps"] == []
