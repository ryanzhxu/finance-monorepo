from __future__ import annotations

from datetime import timezone, datetime

import httpx
from fastapi.testclient import TestClient

from analyst_service.api.main import app
from analyst_service.core import analysis as analysis_module
from analyst_service.core import macro as macro_module
from analyst_service.core import narrator as narrator_module
from analyst_service.core import sentiment as sentiment_module
from tests.test_analyze_integration import (
    _install_fake_yfinance,
    _mock_macro_get,
    _mock_marketaux_headlines,
    _mock_sentiment_sec_get,
)


def test_analyze_returns_json_when_narrative_provider_fails(monkeypatch, tmp_path) -> None:
    _install_fake_yfinance(monkeypatch)
    monkeypatch.setattr(sentiment_module, "_sec_get", _mock_sentiment_sec_get)
    monkeypatch.setattr(sentiment_module, "fetch_marketaux_headlines", _mock_marketaux_headlines)
    monkeypatch.setattr(macro_module.requests, "get", _mock_macro_get)
    monkeypatch.setattr(macro_module, "CACHE_PATH", tmp_path / "fomc-calendar.json")
    monkeypatch.setattr(macro_module, "_today", lambda: macro_module.date(2026, 6, 18))
    monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
    monkeypatch.delenv("REDDIT_CLIENT_SECRET", raising=False)
    monkeypatch.setattr(analysis_module, "append_recommendation", lambda response: None)

    request = httpx.Request("POST", "https://example.com")
    response = httpx.Response(500, request=request)

    async def fail_complete_narrative(prompt: str) -> str:
        raise httpx.HTTPStatusError("provider failed", request=request, response=response)

    monkeypatch.setattr(narrator_module, "complete_narrative", fail_complete_narrative)

    client = TestClient(app)
    result = client.post(
        "/analyze",
        json={
            "symbol": "NVDA",
            "asset_type": "STOCK",
            "horizon": "2-4W",
            "include_narrative": True,
            "include_entry": True,
        },
    )

    assert result.status_code == 200
    payload = result.json()
    assert payload["narrative"] is None
