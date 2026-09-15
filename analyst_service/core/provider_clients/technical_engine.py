"""Pull side of the technical seam: fetch a decision.v1 verdict over HTTP.

The verdict can already be pushed in on the request. This module adds the
symmetric pull: when Ryan's service is asked about a symbol and no verdict was
supplied, it fetches one from Vincent's engine.

On by default, pointed at Vincent's live engine (``DEFAULT_BASE_URL``) —
matching how ``provider_clients/finance_query.py`` defaults to a real provider
rather than requiring opt-in configuration. Set ``TECHNICAL_ENGINE_BASE_URL``
to point elsewhere, or to an empty string to disable the pull and fall back to
local technicals. Any network or protocol failure also returns None, so a slow
or broken engine never takes the analysis down. The returned payload is a raw
dict; validation and rejection stay in ``technical_provider.verdict_from_external``
so a pulled verdict is trusted no more than a pushed one.

Vincent's live endpoint (``GET /decision/<ticker>`` under the configured base
URL, see his PR "feat: serve decision.v1 over HTTP") always returns all three
horizons in one response, nested under ``horizons``, with ``producer`` stated
once at the top level rather than repeated per horizon:

    {"contractVersion": "decision.v1", "producer": "...", "ticker": "...",
     "horizons": {"short": {...}, "mid": {...}, "long": {...}}}

It ignores any ``horizon`` query parameter. This module fetches that payload
once per symbol and reshapes each horizon's object into the flat, per-horizon
shape ``technical_provider.ExternalTechnicalVerdict`` expects (injecting the
top-level ``producer`` into each), rather than issuing one request per
horizon.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Iterable

import httpx

from shared.enums import Horizon

logger = logging.getLogger(__name__)

_ENV_BASE_URL = "TECHNICAL_ENGINE_BASE_URL"
_ENV_TIMEOUT = "TECHNICAL_ENGINE_TIMEOUT"
_ENV_RETRIES = "TECHNICAL_ENGINE_RETRIES"

# Vincent's production Render deployment. See his PR "feat: serve decision.v1
# over HTTP" (stock-decision-dashboard#1).
DEFAULT_BASE_URL = "https://stock-decision-dashboard.onrender.com/api"

_DEFAULT_TIMEOUT = 5.0
# One retry: a single transient hiccup is common, a persistent outage should not
# stall the analysis behind a long retry chain.
_DEFAULT_RETRIES = 1

# Vincent's horizons key, as emitted by decision-v1/emit-decision-v1.js.
_HORIZON_TO_KEY: dict[Horizon, str] = {
    Horizon.ONE_WEEK: "short",
    Horizon.TWO_TO_FOUR_WEEKS: "mid",
    Horizon.THREE_TO_SIX_MONTHS: "long",
}


def technical_engine_base_url() -> str | None:
    """The engine base URL, or None when explicitly disabled.

    Defaults to Vincent's live engine when ``TECHNICAL_ENGINE_BASE_URL`` is
    unset. Setting it to an empty string is the explicit opt-out.
    """
    raw = os.getenv(_ENV_BASE_URL)
    if raw is None:
        return DEFAULT_BASE_URL
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


def _fetch_decision_payload(symbol: str) -> dict[str, Any] | None:
    """Fetch the raw multi-horizon decision.v1 envelope for ``symbol``.

    Returns None when the pull is off, the symbol is blank, every attempt
    fails, or the engine responded with a well-formed but unusable payload
    (a non-object body, or ``{"success": false, ...}`` for a ticker it has no
    decision for).
    """
    base_url = technical_engine_base_url()
    if base_url is None:
        return None

    normalized_symbol = symbol.strip().upper()
    if not normalized_symbol:
        return None

    url = f"{base_url}/decision/{normalized_symbol}"
    timeout = _env_timeout()
    attempts = _env_retries() + 1
    for attempt in range(1, attempts + 1):
        try:
            response = httpx.get(url, timeout=timeout)
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
        if not isinstance(payload, dict):
            logger.warning("technical engine returned a non-object payload for %s; ignoring", normalized_symbol)
            return None
        if payload.get("success") is False:
            logger.warning(
                "technical engine declined %s: %s", normalized_symbol, payload.get("error")
            )
            return None
        return payload
    return None


def _verdict_for_horizon(payload: dict[str, Any], horizon: Any) -> dict[str, Any] | None:
    """Pull one horizon's flat verdict out of the multi-horizon envelope.

    Vincent's per-horizon object has no ``producer`` of its own — the envelope
    states it once. It is injected here so the result validates on its own as
    an ``ExternalTechnicalVerdict``, exactly like a payload pushed on the
    request.
    """
    key = _HORIZON_TO_KEY.get(horizon)
    if key is None:
        return None
    horizons = payload.get("horizons")
    if not isinstance(horizons, dict):
        return None
    verdict = horizons.get(key)
    if not isinstance(verdict, dict):
        return None
    return {
        "contractVersion": payload.get("contractVersion", "decision.v1"),
        "producer": payload.get("producer"),
        **verdict,
    }


def fetch_external_technical_verdict(
    symbol: str, horizon: Any | None = None
) -> dict[str, Any] | None:
    """Fetch a decision.v1 verdict for ``symbol`` at ``horizon``, or None.

    Vincent's engine has no counterpart for a horizon outside short/mid/long
    (e.g. Ryan's ``1D``), so those return None without a network call. Returns
    None when the pull is off, the symbol is blank, every attempt fails, or
    the requested horizon is not in the response.
    """
    if horizon is not None and horizon not in _HORIZON_TO_KEY:
        return None
    payload = _fetch_decision_payload(symbol)
    if payload is None:
        return None
    if horizon is None:
        return payload
    return _verdict_for_horizon(payload, horizon)


def fetch_external_technical_verdicts(symbol: str, horizons: Iterable[Any]) -> dict[Any, dict[str, Any]]:
    """Fetch decision.v1 verdicts for every horizon in ``horizons``, in one call.

    Vincent's engine returns all three horizons in a single response, so this
    fetches once and distributes it rather than issuing one request per
    horizon. A horizon absent from the result means the pull is off, the
    fetch failed, or that horizon has no counterpart in the response.
    """
    payload = _fetch_decision_payload(symbol)
    if payload is None:
        return {}
    results: dict[Any, dict[str, Any]] = {}
    for horizon in horizons:
        verdict = _verdict_for_horizon(payload, horizon)
        if verdict is not None:
            results[horizon] = verdict
    return results
