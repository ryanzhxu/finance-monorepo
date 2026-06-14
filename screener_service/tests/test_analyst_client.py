from __future__ import annotations

import asyncio

import httpx

from shared.enums import Horizon

from screener_service.core import analyst_client


def test_analyst_base_url_adds_https_for_render_host(monkeypatch) -> None:
    monkeypatch.setenv("ANALYST_BASE_URL", "finance-analyst.onrender.com")

    assert analyst_client.analyst_base_url() == "https://finance-analyst.onrender.com"


def test_analyst_base_url_keeps_existing_scheme(monkeypatch) -> None:
    monkeypatch.setenv("ANALYST_BASE_URL", "http://127.0.0.1:8001")

    assert analyst_client.analyst_base_url() == "http://127.0.0.1:8001"


def test_fetch_analysis_returns_none_on_timeout(monkeypatch) -> None:
    class TimeoutClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, *args, **kwargs):
            raise httpx.ReadTimeout("timed out")

    monkeypatch.setattr(analyst_client.httpx, "AsyncClient", TimeoutClient)

    result = asyncio.run(analyst_client.fetch_analysis("NVDA", Horizon.TWO_TO_FOUR_WEEKS))

    assert result is None
