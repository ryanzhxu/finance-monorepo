"""Pull side of the technical seam: fetch a decision.v1 verdict over HTTP.

The verdict can already be pushed in on the request. This module adds the
symmetric pull: when Ryan's service is asked about a symbol and no verdict was
supplied, it can fetch one from Vincent's engine at a configured base URL.

Off by default. Without ``TECHNICAL_ENGINE_BASE_URL`` set, every call returns
None and the analysis degrades to the local technicals exactly as before. Any
network or protocol failure also returns None, so a slow or broken engine never
takes the analysis down. The returned payload is a raw dict; validation and
rejection stay in ``technical_provider.verdict_from_external`` so a pulled
verdict is trusted no more than a pushed one.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Iterable

import httpx

logger = logging.getLogger(__name__)

_ENV_BASE_URL = "TECHNICAL_ENGINE_BASE_URL"
_ENV_TIMEOUT = "TECHNICAL_ENGINE_TIMEOUT"
_ENV_RETRIES = "TECHNICAL_ENGINE_RETRIES"

_DEFAULT_TIMEOUT = 5.0
# One retry: a single transient hiccup is common, a persistent outage should not
# stall the analysis behind a long retry chain.
_DEFAULT_RETRIES = 1


def technical_engine_base_url() -> str | None:
    """The configured engine base URL, or None when the pull is off."""
    raw = os.getenv(_ENV_BASE_URL)
    if raw is None:
        return None
    trimmed = raw.strip().rstrip("/")
    return trimmed or None


def _env_timeout() -> float:
    raw = os.getenv(_ENV_TIMEOUT)
    if raw is None:
        return _DEFAULT_TIMEOUT
    try:
        value = float(raw)
    except ValueError:
        logger.warning("%s is not a number; using %.1fs", _ENV_TIMEOUT, _DEFAULT_TIMEOUT)
        return _DEFAULT_TIMEOUT
    return value if value > 0 else _DEFAULT_TIMEOUT


def _env_retries() -> int:
    raw = os.getenv(_ENV_RETRIES)
    if raw is None:
        return _DEFAULT_RETRIES
    try:
        value = int(raw)
    except ValueError:
        logger.warning("%s is not an integer; using %d", _ENV_RETRIES, _DEFAULT_RETRIES)
        return _DEFAULT_RETRIES
    return value if value >= 0 else _DEFAULT_RETRIES


def fetch_external_technical_verdict(
    symbol: str, horizon: Any | None = None
) -> dict[str, Any] | None:
    """Fetch a decision.v1 verdict for ``symbol``, or None when off/unavailable.

    Returns the raw payload dict on success. Returns None when the pull is off,
    the symbol is blank, or every attempt fails, so the caller falls back to the
    local technicals.
    """
    base_url = technical_engine_base_url()
    if base_url is None:
        return None

    normalized_symbol = symbol.strip().upper()
    if not normalized_symbol:
        return None

    params: dict[str, str] = {}
    if horizon is not None:
        params["horizon"] = horizon.value if hasattr(horizon, "value") else str(horizon)

    url = f"{base_url}/decision/{normalized_symbol}"
    timeout = _env_timeout()
    attempts = _env_retries() + 1
    for attempt in range(1, attempts + 1):
        try:
            response = httpx.get(url, params=params, timeout=timeout)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning(
                "technical engine request for %s failed (attempt %d/%d): %s",
                normalized_symbol,
                attempt,
                attempts,
                exc,
            )
            continue
        if isinstance(payload, dict):
            return payload
        logger.warning("technical engine returned a non-object payload for %s; ignoring", normalized_symbol)
        return None
    return None


def fetch_external_technical_verdicts(symbol: str, horizons: Iterable[Any]) -> dict[Any, dict[str, Any]]:
    """Fetch a decision.v1 verdict per horizon, keyed by the horizon requested.

    Each horizon is an independent call through ``fetch_external_technical_verdict``,
    so one horizon's failure does not affect the others. A horizon is absent from
    the result when the pull is off or that horizon's fetch failed.
    """
    results: dict[Any, dict[str, Any]] = {}
    for horizon in horizons:
        payload = fetch_external_technical_verdict(symbol, horizon)
        if payload is not None:
            results[horizon] = payload
    return results
