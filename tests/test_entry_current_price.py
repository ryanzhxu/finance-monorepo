from __future__ import annotations

from fastapi.testclient import TestClient

from analyst_service.api.main import app
from analyst_service.core import analysis as analysis_module
from analyst_service.core import macro as macro_module
from analyst_service.core import sentiment as sentiment_module
from tests.test_analyze_integration import (
    _install_fake_yfinance,
    _mock_macro_get,
    _mock_sentiment_sec_get,
    _mock_tiingo_news,
)


def test_entry_and_analyze_surface_non_null_current_price(monkeypatch, tmp_path) -> None:
    _install_fake_yfinance(monkeypatch)
    monkeypatch.setattr(sentiment_module, "_sec_get", _mock_sentiment_sec_get)
    monkeypatch.setattr(sentiment_module, "fetch_tiingo_news", _mock_tiingo_news)
    monkeypatch.setattr(sentiment_module, "fetch_yahoo_rss_headlines", lambda symbol: [])
    monkeypatch.setattr(macro_module.requests, "get", _mock_macro_get)
    monkeypatch.setattr(macro_module, "CACHE_PATH", tmp_path / "fomc-calendar.json")
    monkeypatch.setattr(macro_module, "_today", lambda: macro_module.date(2026, 6, 18))
    monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
    monkeypatch.delenv("REDDIT_CLIENT_SECRET", raising=False)
    monkeypatch.setattr(analysis_module, "append_recommendation", lambda response: None)

    client = TestClient(app)

    entry_response = client.post(
        "/entry",
        json={
            "symbol": "NVDA",
            "asset_type": "STOCK",
            "horizon": "2-4W",
        },
    )
    assert entry_response.status_code == 200
    entry_payload = entry_response.json()
    assert isinstance(entry_payload["current_price"], float)
    assert entry_payload["risk_reward_ratio"] is not None

    analyze_response = client.post(
        "/analyze",
        json={
            "symbol": "NVDA",
            "asset_type": "STOCK",
            "horizon": "2-4W",
            "include_narrative": False,
            "include_entry": True,
        },
    )
    assert analyze_response.status_code == 200
    analyze_payload = analyze_response.json()
    assert analyze_payload["technicals"]["dist_from_ma20_pct"] is not None
    assert analyze_payload["technicals"]["dist_from_ma50_pct"] is not None
    assert analyze_payload["technicals"]["dist_from_ma200_pct"] is not None
