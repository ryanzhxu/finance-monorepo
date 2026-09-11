"""Python mirror of cloudflare-api/src/consolidated/index-hurdle.js, for research.

Reads the same config/consolidation.json so the two never drift apart on
thresholds. This is a line-by-line port, not a reinterpretation: see
index-hurdle.js for the rule commentary (benchmarks, the three evidence items,
the earnings guard). Never tune a threshold here — change consolidation.json,
which both sides read.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Callable

_CONFIG_PATH = Path(__file__).resolve().parent.parent / "cloudflare-api" / "config" / "consolidation.json"


def _load_config() -> dict[str, Any]:
    return json.loads(_CONFIG_PATH.read_text())


CONFIG = _load_config()
HURDLE = CONFIG["indexHurdle"]
INDEX_LABELS = {"SPY": "S&P 500", "QQQ": "Nasdaq-100"}


def _round2(value: float) -> float:
    # Matches JS `Math.round(value * 100) / 100` (half rounds toward +Infinity),
    # not Python's banker's-rounding `round()`.
    return math.floor(value * 100 + 0.5) / 100


def resolve_benchmarks(
    symbol: str,
    sector: str | None = None,
    industry: str | None = None,
    traits: list[str] | None = None,
) -> dict[str, Any]:
    normalized = (symbol or "").strip().upper()
    if normalized in HURDLE["notApplicable"]:
        return {"applicable": False, "benchmarks": []}
    benchmarks: list[dict[str, str]] = []

    def add(ticker: str | None, role: str, label: str) -> None:
        if not ticker or ticker == normalized or any(item["symbol"] == ticker for item in benchmarks):
            return
        benchmarks.append({"symbol": ticker, "role": role, "label": label})

    for core in HURDLE["coreBenchmarks"]:
        add(core, "index", INDEX_LABELS.get(core, core))
    for suffix, index in HURDLE["localIndexBySuffix"].items():
        if normalized.endswith(suffix):
            add(index, "local_index", index)
    if sector and sector in HURDLE["sectorEtfs"]:
        add(HURDLE["sectorEtfs"][sector], "sector", sector)
    if industry:
        for etf, industries in HURDLE["industryEtfs"].items():
            if industry in industries:
                add(etf, "industry", industry)
    for trait in traits or []:
        if trait in HURDLE["traitEtfs"]:
            add(HURDLE["traitEtfs"][trait], "industry", trait)
    return {"applicable": True, "benchmarks": benchmarks}


def series_from_bars(bars: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Daily bars -> [{date, close}], preferring dividend-adjusted closes."""
    bars = bars or {}
    dates = bars.get("timestamps") or []
    adj = bars.get("adjCloses") or []
    closes = bars.get("closes") or []
    points = []
    for index, date in enumerate(dates):
        close = adj[index] if index < len(adj) and adj[index] is not None else (closes[index] if index < len(closes) else None)
        if close is not None and math.isfinite(close) and close > 0:
            points.append({"date": date, "close": close})
    return points


def _align(stock_series: list[dict[str, Any]], bench_series: list[dict[str, Any]]) -> list[dict[str, float]]:
    bench_by_date = {point["date"]: point["close"] for point in bench_series}
    pairs = []
    for point in stock_series:
        bench = bench_by_date.get(point["date"])
        if bench is not None:
            pairs.append({"stock": point["close"], "bench": bench})
    return pairs


def _pct_return(frm: float, to: float) -> float:
    return (to / frm - 1) * 100


def relative_evidence(
    stock_series: list[dict[str, Any]] | None,
    bench_series: list[dict[str, Any]] | None,
    windows: dict[str, int] | None = None,
    min_evidence: int | None = None,
) -> dict[str, Any]:
    windows = windows or HURDLE["windows"]
    min_evidence = HURDLE["minEvidence"] if min_evidence is None else min_evidence
    pairs = _align(stock_series or [], bench_series or [])
    last = len(pairs) - 1
    momentum_lookback = windows["momentumLookback"]
    momentum_skip = windows["momentumSkip"]
    six_month = windows["sixMonth"]
    ratio_average = windows["ratioAverage"]

    rel_12_1: float | None = None
    rel_6m: float | None = None
    ratio_above: bool | None = None

    if len(pairs) > momentum_lookback:
        frm = pairs[last - momentum_lookback]
        to = pairs[last - momentum_skip]
        rel_12_1 = _round2(_pct_return(frm["stock"], to["stock"]) - _pct_return(frm["bench"], to["bench"]))
    if len(pairs) > six_month:
        frm = pairs[last - six_month]
        to = pairs[last]
        rel_6m = _round2(_pct_return(frm["stock"], to["stock"]) - _pct_return(frm["bench"], to["bench"]))
    if len(pairs) >= ratio_average:
        ratios = [pair["stock"] / pair["bench"] for pair in pairs[-ratio_average:]]
        average = sum(ratios) / len(ratios)
        ratio_above = ratios[-1] > average

    evidence = [None if rel_12_1 is None else rel_12_1 > 0, None if rel_6m is None else rel_6m > 0, ratio_above]
    known = [value for value in evidence if value is not None]
    true_count = sum(1 for value in known if value)
    false_count = len(known) - true_count
    # Fewer than min_evidence computable items is not evidence either way. A
    # 1-1 split is mixed. Both fail closed: only `beats` passes.
    if len(known) < min_evidence:
        result = "insufficient_data"
    elif true_count >= min_evidence:
        result = "beats"
    elif false_count >= min_evidence:
        result = "lags"
    else:
        result = "mixed"
    return {
        "rel_12_1_pct": rel_12_1,
        "rel_6m_pct": rel_6m,
        "ratio_above_200d": ratio_above,
        "evidence_true": true_count,
        "evidence_known": len(known),
        "sessions": len(pairs),
        "result": result,
    }


def recommendation_net_score(row: dict[str, Any] | None) -> float | None:
    """Share of analysts net bullish in one recommendationTrend row, or None."""
    if not row:
        return None
    strong_buy = row.get("strongBuy") or 0
    buy = row.get("buy") or 0
    hold = row.get("hold") or 0
    sell = row.get("sell") or 0
    strong_sell = row.get("strongSell") or 0
    total = strong_buy + buy + hold + sell + strong_sell
    return (strong_buy + buy - sell - strong_sell) / total if total > 0 else None


def _finite_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def earnings_guard(earnings: dict[str, Any] | None = None) -> dict[str, Any]:
    """Fires only when the latest EPS surprise is negative AND analysts are
    turning against the stock. Without enough data it cannot fire, and says so.
    """
    earnings = earnings or {}
    rows = (earnings.get("recommendationTrend") or {}).get("trend") or []
    now_row = next((row for row in rows if row.get("period") == "0m"), None)
    before_row = next((row for row in rows if row.get("period") == "-3m"), None) or next(
        (row for row in rows if row.get("period") == "-2m"), None
    )
    now_score = recommendation_net_score(now_row)
    before_score = recommendation_net_score(before_row)
    trend_deteriorating = (
        now_score < before_score - HURDLE["earningsGuard"]["minNetDrop"]
        if now_score is not None and before_score is not None
        else None
    )
    upgrades_30d = earnings.get("upgrades30d")
    downgrades_30d = earnings.get("downgrades30d")
    downgrades_lead = downgrades_30d > upgrades_30d if upgrades_30d is not None and downgrades_30d is not None else None
    analysts_known = trend_deteriorating is not None or downgrades_lead is not None
    analysts_deteriorating = trend_deteriorating is True or downgrades_lead is True
    surprise = _finite_or_none(earnings.get("epsSurprisePct"))
    if surprise is None or not analysts_known:
        status = "unavailable"
    elif surprise < 0 and analysts_deteriorating:
        status = "fired"
    else:
        status = "clear"
    return {
        "status": status,
        "eps_surprise_pct": surprise,
        "analysts_deteriorating": analysts_deteriorating if analysts_known else None,
    }


def evaluate_hurdle(
    applicable: bool = True,
    benchmarks: list[dict[str, Any]] | None = None,
    stock_series: list[dict[str, Any]] | None = None,
    benchmark_series: dict[str, list[dict[str, Any]]] | None = None,
    earnings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    benchmarks = benchmarks or []
    stock_series = stock_series or []
    benchmark_series = benchmark_series or {}
    guard = earnings_guard(earnings)
    if not applicable:
        return {"status": "not_applicable", "benchmarks": [], "lagging": [], "earnings_guard": guard}
    if not stock_series or not benchmarks:
        return {
            "status": "unavailable",
            "benchmarks": [],
            "lagging": [item["symbol"] for item in benchmarks],
            "earnings_guard": guard,
        }
    rows = [
        {**benchmark, **relative_evidence(stock_series, benchmark_series.get(benchmark["symbol"], []))}
        for benchmark in benchmarks
    ]
    lagging = [row["symbol"] for row in rows if row["result"] != "beats"]
    status = "pass" if not lagging and guard["status"] != "fired" else "fail"
    return {"status": status, "benchmarks": rows, "lagging": lagging, "earnings_guard": guard}


def run_index_hurdle(
    symbol: str,
    sector: str | None = None,
    industry: str | None = None,
    traits: list[str] | None = None,
    earnings: dict[str, Any] | None = None,
    load_series: Callable[[str], list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    resolved = resolve_benchmarks(symbol, sector, industry, traits)
    if not resolved["applicable"]:
        return evaluate_hurdle(applicable=False, earnings=earnings)
    benchmarks = resolved["benchmarks"]

    def safe_load(item_symbol: str) -> list[dict[str, Any]]:
        # One benchmark that fails to load must not sink the others; it simply
        # has no evidence and fails closed on its own row.
        try:
            return load_series(item_symbol) or []
        except Exception:
            return []

    stock_series = safe_load(symbol)
    benchmark_series = {benchmark["symbol"]: safe_load(benchmark["symbol"]) for benchmark in benchmarks}
    return evaluate_hurdle(
        applicable=True,
        benchmarks=benchmarks,
        stock_series=stock_series,
        benchmark_series=benchmark_series,
        earnings=earnings,
    )
