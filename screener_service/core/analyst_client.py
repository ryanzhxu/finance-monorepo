from __future__ import annotations

import os

import httpx

from shared.enums import Horizon
from shared.models import AnalyzeResponse, EntryBlock


async def fetch_entry(symbol: str, horizon: Horizon) -> EntryBlock | None:
    base_url = os.getenv("ANALYST_BASE_URL", "http://127.0.0.1:8001").rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(f"{base_url}/entry", json={"symbol": symbol, "horizon": horizon.value})
            response.raise_for_status()
        return EntryBlock.model_validate(response.json())
    except Exception:
        return None


async def fetch_analysis(symbol: str, horizon: Horizon) -> AnalyzeResponse | None:
    base_url = os.getenv("ANALYST_BASE_URL", "http://127.0.0.1:8001").rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=20) as client:
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
