from __future__ import annotations

from datetime import datetime, timezone

from analyst_service.core import analysis as analysis_module
from analyst_service.core import persistence
from shared.enums import Direction, Horizon, MarketRegime
from shared.models import AnalyzeResponse, Fundamentals, Macro, Recommendation, Sentiment, Signal, Technicals, MacdBlock


def _response() -> AnalyzeResponse:
    return AnalyzeResponse(
        symbol="NVDA",
        generated_at=datetime(2025, 1, 2, tzinfo=timezone.utc),
        data_freshness={"price": "last_close"},
        data_quality_score=88,
        confidence=0.72,
        technicals=Technicals(macd=MacdBlock()),
        fundamentals=Fundamentals(),
        sentiment=Sentiment(),
        macro=Macro(market_regime=MarketRegime.NEUTRAL),
        signals=[Signal(dimension="Momentum", signal=Direction.BUY, weight=1.0, note="positive")],
        recommendation=Recommendation(
            direction=Direction.BUY,
            confidence=0.72,
            signal_vote={Direction.BUY: 1.0},
            weighted_score=0.72,
            horizon=Horizon.TWO_TO_FOUR_WEEKS,
            review_action="add_watch",
        ),
    )


def test_persisted_analysis_round_trips_from_sqlite(tmp_path) -> None:
    database_path = tmp_path / "analysis.sqlite3"

    assert persistence.persist_analysis(_response(), database_path) is True

    records = persistence.load_persisted_analyses(database_path)

    assert len(records) == 1
    assert records[0].symbol == "NVDA"
    assert records[0].horizon == "2-4W"
    assert records[0].payload["recommendation"]["direction"] == "BUY"


def test_analysis_logging_failure_does_not_escape(monkeypatch) -> None:
    response = _response()

    def fail_append(_response) -> None:
        raise OSError("disk unavailable")

    monkeypatch.setattr(analysis_module, "append_recommendation", fail_append)
    monkeypatch.setattr(analysis_module, "persist_analysis", lambda _response: False)

    analysis_module._persist_analysis(response)
