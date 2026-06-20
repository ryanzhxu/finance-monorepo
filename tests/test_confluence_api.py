from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
from fastapi.testclient import TestClient

from analyst_service.api.main import app
from analyst_service.api.routers import analysis as analysis_router
from analyst_service.core.fibonacci import FibonacciResult
from shared.data_quality import FreshValue
from shared.enums import Freshness
from shared.models import EntryConfluenceResponse, Fundamentals, Macro, Sentiment


def _ohlcv_frame() -> pd.DataFrame:
    dates = pd.bdate_range(end="2026-06-18", periods=40)
    close = pd.Series([100.0 + (index * 0.5) for index in range(40)], index=dates)
    open_ = close.shift(1).fillna(close.iloc[0] * 0.99)
    return pd.DataFrame(
        {
            "open": open_,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": 1_000_000.0,
        },
        index=dates,
    )


def _fake_fibonacci() -> FibonacciResult:
    return FibonacciResult(
        swing_high=120.0,
        swing_low=90.0,
        level_0=120.0,
        level_236=112.92,
        level_382=108.54,
        level_500=105.0,
        level_618=101.46,
        level_650=100.5,
        level_786=96.42,
        level_1000=90.0,
        golden_pocket_low=100.5,
        golden_pocket_high=101.46,
        as_of="2026-06-18",
        lookback_days=90,
    )


def _mock_fetch_analysis_context(symbol: str, price_history: pd.DataFrame):
    del symbol, price_history
    now = datetime(2026, 6, 18, tzinfo=timezone.utc)
    return (
        FreshValue(Fundamentals(), Freshness.QUARTERLY, now),
        FreshValue(Sentiment(), Freshness.DELAYED, now),
        FreshValue(Macro(), Freshness.DELAYED, now),
    )


def test_post_entry_confluence_returns_valid_response(monkeypatch) -> None:
    monkeypatch.setattr(
        analysis_router,
        "fetch_ohlcv",
        lambda symbol, current_price=None: FreshValue(_ohlcv_frame(), Freshness.DELAYED, datetime(2026, 6, 18, tzinfo=timezone.utc)),
    )
    monkeypatch.setattr(analysis_router, "fetch_analysis_context", _mock_fetch_analysis_context)
    monkeypatch.setattr(analysis_router, "compute_fibonacci_levels", lambda symbol, price_df, lookback_days: _fake_fibonacci())

    client = TestClient(app)
    response = client.post("/entry/confluence", json={"symbol": "NVDA"})

    assert response.status_code == 200
    EntryConfluenceResponse.model_validate(response.json())


def test_get_entry_confluence_by_symbol(monkeypatch) -> None:
    monkeypatch.setattr(
        analysis_router,
        "fetch_ohlcv",
        lambda symbol, current_price=None: FreshValue(_ohlcv_frame(), Freshness.DELAYED, datetime(2026, 6, 18, tzinfo=timezone.utc)),
    )
    monkeypatch.setattr(analysis_router, "fetch_analysis_context", _mock_fetch_analysis_context)
    monkeypatch.setattr(analysis_router, "compute_fibonacci_levels", lambda symbol, price_df, lookback_days: _fake_fibonacci())

    client = TestClient(app)
    response = client.get("/entry/confluence/NVDA")

    assert response.status_code == 200
    EntryConfluenceResponse.model_validate(response.json())
