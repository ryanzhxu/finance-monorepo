"""Parity tests for backtesting/index_hurdle.py against
cloudflare-api/src/consolidated/index-hurdle.js and cloudflare-api/test/
consolidated-hurdle.test.mjs. Every case here mirrors a case in the JS test
file; the expected values must match exactly (this is a port, not a
reinterpretation). Not collected by the main `pytest -q` run (see
pyproject.toml testpaths) — run directly:
  UV_CACHE_DIR=/private/tmp/uv-cache uv run --no-sync pytest backtesting/tests/test_index_hurdle.py -q
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

from backtesting.index_hurdle import (
    earnings_guard,
    evaluate_hurdle,
    relative_evidence,
    resolve_benchmarks,
    run_index_hurdle,
)

FIXTURES_DIR = Path(__file__).resolve().parent.parent.parent / "contracts" / "consolidated" / "fixtures"


def series(length: int, daily_pct: float, start: float = 100.0) -> list[dict]:
    base = date(2024, 1, 1)
    return [
        {"date": (base + timedelta(days=index)).isoformat(), "close": start * (1 + daily_pct / 100) ** index}
        for index in range(length)
    ]


def test_benchmarks_are_spy_qqq_sector_and_industry_without_duplicates():
    result = resolve_benchmarks("NVDA", sector="Technology", industry="Semiconductors", traits=["Semiconductor", "GPU"])
    assert result["applicable"] is True
    assert [(item["symbol"], item["role"]) for item in result["benchmarks"]] == [
        ("SPY", "index"),
        ("QQQ", "index"),
        ("XLK", "sector"),
        ("SMH", "industry"),
    ]


def test_a_broad_index_etf_is_the_benchmark_so_the_hurdle_does_not_apply_to_it():
    assert resolve_benchmarks("SPY") == {"applicable": False, "benchmarks": []}
    assert resolve_benchmarks("voo")["applicable"] is False


def test_a_ticker_is_never_its_own_benchmark():
    assert [item["symbol"] for item in resolve_benchmarks("QQQ")["benchmarks"]] == ["SPY"]
    assert [item["symbol"] for item in resolve_benchmarks("SMH", sector="Technology", industry="Semiconductors")["benchmarks"]] == [
        "SPY",
        "QQQ",
        "XLK",
    ]


def test_a_hong_kong_listing_also_has_to_beat_its_local_index():
    symbols = [item["symbol"] for item in resolve_benchmarks("0700.HK")["benchmarks"]]
    assert symbols == ["SPY", "QQQ", "^HSI"]


def test_a_stock_that_compounds_faster_than_the_benchmark_beats_it_on_all_three_evidence_items():
    evidence = relative_evidence(series(300, 0.12), series(300, 0.04))
    assert evidence["result"] == "beats"
    assert evidence["evidence_true"] == 3
    assert evidence["rel_12_1_pct"] > 0
    assert evidence["rel_6m_pct"] > 0
    assert evidence["ratio_above_200d"] is True


def test_a_stock_that_compounds_slower_than_the_benchmark_lags_it():
    evidence = relative_evidence(series(300, 0.01), series(300, 0.06))
    assert evidence["result"] == "lags"
    assert evidence["rel_12_1_pct"] < 0


def test_a_short_history_is_not_evidence_either_way():
    assert relative_evidence(series(100, 0.2), series(100, 0.01))["result"] == "insufficient_data"
    partial = relative_evidence(series(150, 0.2), series(150, 0.01))
    assert partial["rel_12_1_pct"] is None
    assert partial["rel_6m_pct"] is not None
    assert partial["result"] == "insufficient_data"


def test_a_1_1_split_between_the_computable_items_is_mixed_not_beats():
    def ratio(t: int) -> float:
        if t <= 100:
            return 1 + 0.2 * (t / 100)
        if t <= 180:
            return 1.2 + 0.4 * ((t - 100) / 80)
        return 1.6 - 0.35 * ((t - 180) / 49)

    dates = [point["date"] for point in series(230, 0)]
    stock = [{"date": d, "close": 100 * ratio(t)} for t, d in enumerate(dates)]
    bench = [{"date": d, "close": 100} for d in dates]
    evidence = relative_evidence(stock, bench)
    assert evidence["rel_12_1_pct"] is None
    assert evidence["rel_6m_pct"] > 0
    assert evidence["ratio_above_200d"] is False
    assert evidence["result"] == "mixed"


def test_the_earnings_guard_fires_only_on_a_negative_surprise_with_analysts_turning_bearish():
    assert earnings_guard({"epsSurprisePct": -4, "upgrades30d": 0, "downgrades30d": 2})["status"] == "fired"
    assert earnings_guard({"epsSurprisePct": 3, "upgrades30d": 0, "downgrades30d": 2})["status"] == "clear"
    assert earnings_guard({"epsSurprisePct": -4, "upgrades30d": 2, "downgrades30d": 0})["status"] == "clear"
    assert earnings_guard({})["status"] == "unavailable"
    trend = {
        "trend": [
            {"period": "0m", "strongBuy": 1, "buy": 2, "hold": 5, "sell": 2, "strongSell": 0},
            {"period": "-3m", "strongBuy": 4, "buy": 4, "hold": 2, "sell": 0, "strongSell": 0},
        ],
    }
    assert earnings_guard({"epsSurprisePct": -1, "recommendationTrend": trend})["status"] == "fired"


def test_the_hurdle_passes_only_when_every_benchmark_is_beaten():
    benchmarks = [
        {"symbol": "SPY", "role": "index", "label": "S&P 500"},
        {"symbol": "SMH", "role": "industry", "label": "Semiconductors"},
    ]
    stock_series = series(300, 0.1)
    passing = evaluate_hurdle(
        benchmarks=benchmarks,
        stock_series=stock_series,
        benchmark_series={"SPY": series(300, 0.03), "SMH": series(300, 0.05)},
    )
    assert passing["status"] == "pass"
    assert passing["lagging"] == []

    failing = evaluate_hurdle(
        benchmarks=benchmarks,
        stock_series=stock_series,
        benchmark_series={"SPY": series(300, 0.03), "SMH": series(300, 0.2)},
    )
    assert failing["status"] == "fail"
    assert failing["lagging"] == ["SMH"]


def test_a_fired_earnings_guard_fails_a_hurdle_that_every_benchmark_passes():
    result = evaluate_hurdle(
        benchmarks=[{"symbol": "SPY", "role": "index", "label": "S&P 500"}],
        stock_series=series(300, 0.1),
        benchmark_series={"SPY": series(300, 0.02)},
        earnings={"epsSurprisePct": -5, "upgrades30d": 0, "downgrades30d": 3},
    )
    assert result["status"] == "fail"
    assert result["lagging"] == []
    assert result["earnings_guard"]["status"] == "fired"


def test_a_benchmark_that_fails_to_load_fails_closed_on_its_own_row():
    loads = {
        "NVDA": series(300, 0.1),
        "SPY": series(300, 0.02),
        "QQQ": series(300, 0.03),
        "XLK": series(300, 0.03),
    }

    def load_series(symbol: str) -> list[dict]:
        if symbol not in loads:
            raise RuntimeError("offline")
        return loads[symbol]

    result = run_index_hurdle("NVDA", sector="Technology", industry="Semiconductors", load_series=load_series)
    assert result["status"] == "fail"
    assert result["lagging"] == ["SMH"]
    assert next(row for row in result["benchmarks"] if row["symbol"] == "SMH")["result"] == "insufficient_data"


def test_with_no_stock_history_the_hurdle_is_unavailable():
    result = evaluate_hurdle(benchmarks=[{"symbol": "SPY", "role": "index", "label": "S&P 500"}], stock_series=[])
    assert result["status"] == "unavailable"


def _hurdle_status_from_rows(rows: list[dict], guard_status: str) -> tuple[str, list[str]]:
    """Reimplements evaluateHurdle's tail (status/lagging derivation from
    already-scored benchmark rows), so a fixture's stored index_hurdle block
    can be checked for internal consistency without needing the raw daily
    series that produced it (fixtures store the evaluated output only).
    """
    lagging = [row["symbol"] for row in rows if row["result"] != "beats"]
    status = "pass" if not lagging and guard_status != "fired" else "fail"
    return status, lagging


def test_contract_fixtures_index_hurdle_blocks_are_internally_consistent():
    fixture_paths = sorted(FIXTURES_DIR.glob("*.json"))
    assert fixture_paths, f"no fixtures found under {FIXTURES_DIR}"
    checked = 0
    for path in fixture_paths:
        payload = json.loads(path.read_text())
        hurdle = payload.get("index_hurdle")
        if not hurdle or hurdle["status"] not in ("pass", "fail"):
            continue
        checked += 1
        for row in hurdle["benchmarks"]:
            true_count = row["evidence_true"]
            known = row["evidence_known"]
            min_evidence = 2  # consolidation.json indexHurdle.minEvidence
            false_count = known - true_count
            if known < min_evidence:
                expected_result = "insufficient_data"
            elif true_count >= min_evidence:
                expected_result = "beats"
            elif false_count >= min_evidence:
                expected_result = "lags"
            else:
                expected_result = "mixed"
            assert row["result"] == expected_result, (
                f"{path.name}: {row['symbol']} evidence_true={true_count} evidence_known={known} "
                f"stored result={row['result']!r}, recomputed={expected_result!r}"
            )
        status, lagging = _hurdle_status_from_rows(hurdle["benchmarks"], hurdle["earnings_guard"]["status"])
        assert status == hurdle["status"], f"{path.name}: stored status={hurdle['status']!r}, recomputed={status!r}"
        assert lagging == hurdle["lagging"], f"{path.name}: stored lagging={hurdle['lagging']!r}, recomputed={lagging!r}"
    assert checked >= 2, "expected at least the pass and fail fixtures to be checked"
