from __future__ import annotations

import os
from urllib.parse import urlsplit

import httpx

from shared.enums import Horizon
from shared.models import AnalyzeResponse, EntryBlock


DEFAULT_ANALYST_BASE_URL = "http://127.0.0.1:8001"
ANALYST_TIMEOUT = httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0)


def analyst_base_url() -> str:
    raw_base_url = os.getenv("ANALYST_BASE_URL", DEFAULT_ANALYST_BASE_URL).strip().rstrip("/")
    if not raw_base_url:
        raw_base_url = DEFAULT_ANALYST_BASE_URL
    if urlsplit(raw_base_url).scheme:
        return raw_base_url
    return f"https://{raw_base_url}"


async def fetch_entry(symbol: str, horizon: Horizon) -> EntryBlock | None:
    base_url = analyst_base_url()
    try:
        async with httpx.AsyncClient(timeout=ANALYST_TIMEOUT) as client:
            response = await client.post(f"{base_url}/entry", json={"symbol": symbol, "horizon": horizon.value})
            response.raise_for_status()
        return EntryBlock.model_validate(response.json())
    except Exception:
        return None


async def fetch_analysis(symbol: str, horizon: Horizon) -> AnalyzeResponse | None:
    base_url = analyst_base_url()
    try:
        async with httpx.AsyncClient(timeout=ANALYST_TIMEOUT) as client:
            response = await client.post(
                f"{base_url}/analyze",
                json={
                    "symbol": symbol,
                    "horizon": horizon.value,
                    "include_entry": True,
                    "include_narrative": False,
                },
            )
            response.raise_for_status()
        return AnalyzeResponse.model_validate(response.json())
    except Exception:
        return None
