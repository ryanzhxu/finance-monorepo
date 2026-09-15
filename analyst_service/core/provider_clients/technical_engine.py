"""Pull side of the technical seam: fetch a decision.v1 verdict over HTTP.

The verdict can already be pushed in on the request. This module adds the
symmetric pull: when Ryan's service is asked about a symbol and no verdict was
supplied, it fetches one from Vincent's engine.

Always pointed at Vincent's live engine (``DEFAULT_BASE_URL``) unless
``TECHNICAL_ENGINE_BASE_URL`` overrides it; there is no way to disable the pull
and degrade to local technicals — a hard dependency, not a best-effort one.
Any network or protocol failure raises ``TechnicalEngineUnavailable`` rather
than returning None, so a broken engine fails the analysis loudly instead of
quietly substituting a different opinion. The returned payload is a raw dict;
validation and rejection stay in ``technical_provider.verdict_from_external``
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


class TechnicalEngineUnavailable(RuntimeError):
    """Vincent's engine could not be reached or would not answer for this symbol."""


_ENV_BASE_URL = "TECHNICAL_ENGINE_BASE_URL"
_ENV_TIMEOUT = "TECHNICAL_ENGINE_TIMEOUT"
_ENV_RETRIES = "TECHNICAL_ENGINE_RETRIES"
_ENV_API_KEY = "TECHNICAL_ENGINE_API_KEY"

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


def technical_engine_base_url() -> str:
    """The engine base URL. Always resolves to a real URL — there is no opt-out.

    Defaults to Vincent's live engine when ``TECHNICAL_ENGINE_BASE_URL`` is
    unset or blank; otherwise uses the override.
    """
    raw = os.getenv(_ENV_BASE_URL)
    if raw is None:
        return DEFAULT_BASE_URL
    trimmed = raw.strip().rstrip("/")
    return trimmed or DEFAULT_BASE_URL


def _auth_headers() -> dict[str, str]:
    """The bearer header for Vincent's decision endpoints, if a key is set.

    Sending it is forward-compatible with his server enforcing it; not
    requiring it is intentional until he adds that check on his side (his
    engine is imported into this repo read-only — enforcement is a change on
    his own deployment, not something this client can also gate on yet).
    """
    key = os.getenv(_ENV_API_KEY)
    if not key:
        logger.warning("%s is not set; calling Vincent's engine unauthenticated", _ENV_API_KEY)
        return {}
    return {"Authorization": f"Bearer {key}"}


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


def _fetch_decision_payload(symbol: str) -> dict[str, Any]:
    """Fetch the raw multi-horizon decision.v1 envelope for ``symbol``, or raise.

    Raises ``TechnicalEngineUnavailable`` when every attempt fails, or the
    engine responded with a well-formed but unusable payload (a non-object
    body, or ``{"success": false, ...}`` for a ticker it has no decision for).
    """
    normalized_symbol = symbol.strip().upper()
    if not normalized_symbol:
        raise ValueError("symbol is required")

    base_url = technical_engine_base_url()
    url = f"{base_url}/decision/{normalized_symbol}"
    timeout = _env_timeout()
    attempts = _env_retries() + 1
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            response = httpx.get(url, timeout=timeout, headers=_auth_headers())
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            last_error = exc
            logger.warning(
                "technical engine request for %s failed (attempt %d/%d): %s",
                normalized_symbol,
                attempt,
                attempts,
                exc,
            )
            continue
        if not isinstance(payload, dict):
            raise TechnicalEngineUnavailable(
                f"technical engine returned a non-object payload for {normalized_symbol}"
            )
        if payload.get("success") is False:
            raise TechnicalEngineUnavailable(
                f"technical engine declined {normalized_symbol}: {payload.get('error')}"
            )
        return payload
    raise TechnicalEngineUnavailable(
        f"technical engine request for {normalized_symbol} failed after {attempts} attempt(s): {last_error}"
    )


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
    """Fetch a decision.v1 verdict for ``symbol`` at ``horizon``.

    Vincent's engine has no counterpart for a horizon outside short/mid/long
    (e.g. Ryan's ``1D``); that is a structural gap, not a failure, so it
    returns None without a network call. A real attempt (the horizon is one
    his engine covers) that fails raises ``TechnicalEngineUnavailable``
    instead of returning None, so a broken engine cannot masquerade as "no
    opinion for this horizon".
    """
    if horizon is not None and horizon not in _HORIZON_TO_KEY:
        return None
    payload = _fetch_decision_payload(symbol)
    if horizon is None:
        return payload
    return _verdict_for_horizon(payload, horizon)


def fetch_external_technical_verdicts(symbol: str, horizons: Iterable[Any]) -> dict[Any, dict[str, Any]]:
    """Fetch decision.v1 verdicts for every horizon in ``horizons``, in one call.

    Vincent's engine returns all three horizons in a single response, so this
    fetches once and distributes it rather than issuing one request per
    horizon. Raises ``TechnicalEngineUnavailable`` if the fetch itself fails;
    a horizon absent from an otherwise-successful response is still omitted
    from the result rather than fabricated, since that is a content gap in a
    valid reply, not evidence the engine is down.
    """
    payload = _fetch_decision_payload(symbol)
    results: dict[Any, dict[str, Any]] = {}
    for horizon in horizons:
        verdict = _verdict_for_horizon(payload, horizon)
        if verdict is not None:
            results[horizon] = verdict
    return results
