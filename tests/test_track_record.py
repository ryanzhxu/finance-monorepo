"""The track record Vincent asked for twice.

2026-07-24: 「加个history功…在dashboard里面 然后做回测」
2026-07-27: 「比如meta半个月前680 现在600以下. 如果半个月前告诉我卖就牛了」

Every /analyze call has been persisting to SQLite, and backtesting/evaluator.py
has been able to score those calls against what the market actually did — but
nothing imported it, so none of it was reachable. These tests cover the layer
that makes it answerable.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pandas as pd
import pytest

from analyst_service.core.persistence import AnalysisStore, PersistedAnalysis, load_persisted_analyses
from backtesting.price_cache import BatchPriceLoader
from backtesting.track_record import _advisory, performance_report, store_coverage, symbol_timeline


def _record(symbol: str, days_ago: int, direction: str = "BUY", confidence: float = 0.8) -> PersistedAnalysis:
    return PersistedAnalysis(
        id=0,
        symbol=symbol,
        generated_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
        horizon="2-4W",
        direction=direction,
        confidence=confidence,
        weighted_score=0.5,
        data_quality_score=90,
        entry_assessment="buy_now",
        current_price=100.0,
        payload={},
    )


def _rising_prices(symbol: str, start: date, end: date) -> pd.Series:
    index = pd.date_range(start=start, end=end, freq="D")
    return pd.Series([100.0 + i for i in range(len(index))], index=index)


def _falling_prices(symbol: str, start: date, end: date) -> pd.Series:
    index = pd.date_range(start=start, end=end, freq="D")
    return pd.Series([200.0 - i for i in range(len(index))], index=index)


# --- persistence filtering --------------------------------------------------


def _seed(tmp_path, records: list[PersistedAnalysis]):
    from shared.enums import Direction, Horizon
    from shared.models import AnalyzeResponse, Fundamentals, Macro, MacdBlock, Recommendation, Sentiment, Technicals

    store_path = tmp_path / "analysis.sqlite3"
    store = AnalysisStore(store_path)
    for record in records:
        store.save(
            AnalyzeResponse(
                symbol=record.symbol,
                generated_at=record.generated_at,
                data_freshness={},
                data_quality_score=record.data_quality_score,
                confidence=record.confidence,
                technicals=Technicals(macd=MacdBlock()),
                fundamentals=Fundamentals(),
                sentiment=Sentiment(),
                macro=Macro(),
                signals=[],
                recommendation=Recommendation(
                    direction=Direction(record.direction),
                    confidence=record.confidence,
                    signal_vote={},
                    weighted_score=record.weighted_score,
                    horizon=Horizon(record.horizon),
                    review_action="add_watch",
                ),
            )
        )
    return store_path


def test_filter_by_symbol(tmp_path) -> None:
    path = _seed(tmp_path, [_record("META", 30), _record("NVDA", 30), _record("META", 20)])

    assert len(load_persisted_analyses(path)) == 3
    assert len(load_persisted_analyses(path, symbol="META")) == 2
    assert {r.symbol for r in load_persisted_analyses(path, symbol="META")} == {"META"}


def test_filter_by_symbol_is_case_insensitive(tmp_path) -> None:
    path = _seed(tmp_path, [_record("META", 30)])

    assert len(load_persisted_analyses(path, symbol="meta")) == 1


def test_filter_by_since(tmp_path) -> None:
    path = _seed(tmp_path, [_record("META", 90), _record("META", 5)])
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)

    assert len(load_persisted_analyses(path, since=cutoff)) == 1


def test_limit_returns_the_most_recent(tmp_path) -> None:
    path = _seed(tmp_path, [_record("META", 90), _record("META", 60), _record("META", 1)])

    recent = load_persisted_analyses(path, limit=1)

    assert len(recent) == 1
    # Newest, not oldest — a timeline that truncates to the oldest is useless.
    assert (datetime.now(timezone.utc) - recent[0].generated_at).days < 5


def test_defaults_are_unchanged(tmp_path) -> None:
    path = _seed(tmp_path, [_record("META", 30), _record("NVDA", 10)])

    records = load_persisted_analyses(path)

    assert len(records) == 2
    assert records[0].generated_at <= records[1].generated_at


# --- batched price loading --------------------------------------------------


def test_batch_loader_fetches_each_symbol_once() -> None:
    calls: list[str] = []

    def counting_loader(symbol: str, start: date, end: date) -> pd.Series:
        calls.append(symbol)
        return _rising_prices(symbol, start, end)

    records = [_record("META", 40), _record("META", 30), _record("META", 20), _record("NVDA", 25)]
    loader = BatchPriceLoader(counting_loader, records, benchmark_symbol="SPY")
    for record in records:
        loader(record.symbol, record.generated_at.date(), record.generated_at.date() + timedelta(days=120))
    loader("SPY", date(2026, 1, 1), date(2026, 3, 1))

    # Unbatched this is two provider calls per record. Batched it is one per
    # distinct symbol, which is what makes an HTTP endpoint viable.
    assert sorted(calls) == ["META", "NVDA", "SPY"]


def test_batch_loader_slices_match_the_unbatched_loader() -> None:
    records = [_record("META", 40)]
    loader = BatchPriceLoader(_rising_prices, records, benchmark_symbol="SPY")
    start = records[0].generated_at.date()
    end = start + timedelta(days=30)

    batched = loader("META", start, end)
    direct = _rising_prices("META", start, end)

    assert list(batched.index) == list(direct.index)
    assert list(batched.values) == list(direct.values)


def test_batch_loader_survives_a_failing_symbol() -> None:
    def flaky(symbol: str, start: date, end: date) -> pd.Series:
        if symbol == "BAD":
            raise RuntimeError("provider down")
        return _rising_prices(symbol, start, end)

    records = [_record("BAD", 30), _record("META", 30)]
    loader = BatchPriceLoader(flaky, records, benchmark_symbol="SPY")

    # One dead symbol must not take the whole report down.
    assert loader("BAD", date(2026, 1, 1), date(2026, 2, 1)).empty
    assert not loader("META", date(2026, 1, 1), date(2026, 2, 1)).empty


# --- the timeline and the report -------------------------------------------


def test_symbol_timeline_scores_past_calls(tmp_path) -> None:
    path = _seed(tmp_path, [_record("META", 40, direction="SELL")])

    timeline = symbol_timeline("META", path=path, price_loader=_falling_prices)

    assert len(timeline) == 1
    entry = timeline[0]
    assert entry.symbol == "META"
    assert entry.direction == "SELL"
    # Price fell after a SELL, so the call was right.
    assert entry.hit is True


def test_symbol_timeline_is_newest_first(tmp_path) -> None:
    path = _seed(tmp_path, [_record("META", 60), _record("META", 10)])

    timeline = symbol_timeline("META", path=path, price_loader=_rising_prices)

    assert timeline[0].generated_at > timeline[1].generated_at


def test_timeline_for_an_unknown_symbol_is_empty_not_an_error(tmp_path) -> None:
    path = _seed(tmp_path, [_record("META", 30)])

    assert symbol_timeline("TSLA", path=path, price_loader=_rising_prices) == []


def test_performance_report_buckets_by_confidence(tmp_path) -> None:
    path = _seed(
        tmp_path,
        [
            _record("META", 40, direction="BUY", confidence=0.9),
            _record("NVDA", 40, direction="BUY", confidence=0.3),
        ],
    )

    report = performance_report(path=path, price_loader=_rising_prices)

    labels = {bucket.label for bucket in report.by_confidence}
    assert "0.8-1.0" in labels
    assert "0.0-0.5" in labels


def test_confidence_buckets_answer_whether_confidence_means_anything(tmp_path) -> None:
    # High-confidence BUYs into a rising market, low-confidence BUYs into a
    # falling one. If the buckets do not separate, the field is decoration.
    path = _seed(tmp_path, [_record("UP", 40, "BUY", 0.9), _record("DOWN", 40, "BUY", 0.3)])

    def split(symbol: str, start: date, end: date) -> pd.Series:
        return _rising_prices(symbol, start, end) if symbol in ("UP", "SPY") else _falling_prices(symbol, start, end)

    report = performance_report(path=path, price_loader=split)
    by_label = {bucket.label: bucket for bucket in report.by_confidence}

    assert by_label["0.8-1.0"].hit_rate == 1.0
    assert by_label["0.0-0.5"].hit_rate == 0.0


def test_report_on_an_empty_store_is_honest(tmp_path) -> None:
    path = tmp_path / "empty.sqlite3"

    report = performance_report(path=path, price_loader=_rising_prices)

    assert report.evaluated_count == 0
    assert report.hit_rate is None
    # A thin sample must read as thin, not as a confident number.
    assert report.advisory


def test_advisory_thresholds_guard_against_reading_a_thin_sample_as_a_verdict() -> None:
    # The module's whole safety claim: a hit rate over a handful of records must
    # not read as a verdict. This pins the threshold (20, mirroring the
    # evaluator's) so a regression that lowered it — letting a thin sample
    # present as actionable — is caught.
    nothing = " ".join(_advisory(0))
    assert "measurable" in nothing

    # Anywhere below the threshold: the count is named and weight tuning is
    # explicitly forbidden.
    for count in (1, 4, 19):
        thin = " ".join(_advisory(count))
        assert str(count) in thin
        assert "provisional" in thin
        assert "Do not tune signal weights on this sample." in _advisory(count)

    # At and beyond the threshold the sample is no longer flagged as thin, so
    # the "do not tune" warning must be gone.
    for count in (20, 100):
        thick = " ".join(_advisory(count))
        assert "provisional" not in thick
        assert "Do not tune signal weights on this sample." not in _advisory(count)


def test_coverage_needs_no_price_provider(tmp_path) -> None:
    path = _seed(tmp_path, [_record("META", 30), _record("NVDA", 10), _record("META", 5)])

    coverage = store_coverage(path=path)

    assert coverage.record_count == 3
    assert coverage.distinct_symbols == 2
    assert coverage.earliest is not None and coverage.latest is not None


def test_coverage_on_an_empty_store(tmp_path) -> None:
    coverage = store_coverage(path=tmp_path / "nothing.sqlite3")

    assert coverage.record_count == 0
    assert coverage.distinct_symbols == 0
    assert coverage.earliest is None


# --- API routes -------------------------------------------------------------


def test_history_routes_are_registered() -> None:
    from analyst_service.api.main import app

    paths = {route.path for route in app.routes}
    assert "/history/coverage" in paths
    assert "/history/performance" in paths
    assert "/history/{symbol}" in paths


def test_coverage_endpoint_makes_no_provider_call(monkeypatch, tmp_path) -> None:
    from fastapi.testclient import TestClient

    from analyst_service.api.main import app
    import backtesting.track_record as track_record_module

    monkeypatch.setenv("ANALYSIS_STORE_PATH", str(tmp_path / "analysis.sqlite3"))

    def explode(*args, **kwargs):
        raise AssertionError("coverage must not touch a price provider")

    monkeypatch.setattr(track_record_module, "fetch_adjusted_close_history", explode)

    response = TestClient(app).get("/history/coverage")

    assert response.status_code == 200
    assert response.json()["record_count"] == 0


def test_unknown_symbol_returns_an_empty_timeline_not_404(monkeypatch, tmp_path) -> None:
    from fastapi.testclient import TestClient

    from analyst_service.api.main import app

    monkeypatch.setenv("ANALYSIS_STORE_PATH", str(tmp_path / "analysis.sqlite3"))

    response = TestClient(app).get("/history/ZZZZ")

    assert response.status_code == 200
    assert response.json()["entries"] == []
