from __future__ import annotations

import httpx
import pytest

from shared.enums import Direction, Horizon, TechnicalSource
from shared.models import ExternalTechnicalVerdict

from analyst_service.core.provider_clients import technical_engine
from analyst_service.core.technical_provider import resolve_technical_verdict

BASE_URL_ENV = "TECHNICAL_ENGINE_BASE_URL"


def _payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "contractVersion": "decision.v1",
        "producer": "vincent-stock-decision-dashboard",
        "action": "buy",
        "confidence": 70,
        "priceState": "IN_OPPORTUNITY_ZONE",
        "opportunityRange": {"low": 100.0, "high": 110.0},
        "reduceRange": {"low": 140.0, "high": 150.0},
        "invalidation": 95.0,
        "reasons": ["Weekly trend intact"],
        "dataQuality": 88,
    }
    payload.update(overrides)
    return payload


class _FakeResponse:
    def __init__(self, payload: object) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        return self._payload


def test_off_by_default_returns_none_without_calling_out(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(BASE_URL_ENV, raising=False)

    def forbidden(*args: object, **kwargs: object) -> object:
        raise AssertionError("pull must not touch the network when off")

    monkeypatch.setattr(technical_engine.httpx, "get", forbidden)
    assert technical_engine.fetch_external_technical_verdict("NVDA", Horizon.TWO_TO_FOUR_WEEKS) is None


def test_pulls_payload_and_builds_the_url_with_horizon(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(BASE_URL_ENV, "https://engine.example/api/")
    captured: dict[str, object] = {}

    def fake_get(url: str, params: dict[str, str], timeout: float) -> _FakeResponse:
        captured["url"] = url
        captured["params"] = params
        captured["timeout"] = timeout
        return _FakeResponse(_payload())

    monkeypatch.setattr(technical_engine.httpx, "get", fake_get)
    result = technical_engine.fetch_external_technical_verdict("nvda", Horizon.TWO_TO_FOUR_WEEKS)

    assert isinstance(result, dict)
    assert result["action"] == "buy"
    # Trailing slash trimmed, symbol upper-cased, horizon forwarded.
    assert captured["url"] == "https://engine.example/api/decision/NVDA"
    assert captured["params"] == {"horizon": "2-4W"}


def test_blank_symbol_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(BASE_URL_ENV, "https://engine.example")

    def forbidden(*args: object, **kwargs: object) -> object:
        raise AssertionError("blank symbol must not touch the network")

    monkeypatch.setattr(technical_engine.httpx, "get", forbidden)
    assert technical_engine.fetch_external_technical_verdict("   ") is None


def test_network_failure_retries_then_falls_back_to_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(BASE_URL_ENV, "https://engine.example")
    monkeypatch.setenv("TECHNICAL_ENGINE_RETRIES", "2")
    calls = {"n": 0}

    def failing_get(*args: object, **kwargs: object) -> object:
        calls["n"] += 1
        raise httpx.HTTPError("boom")

    monkeypatch.setattr(technical_engine.httpx, "get", failing_get)
    assert technical_engine.fetch_external_technical_verdict("NVDA") is None
    # 2 retries means 3 attempts total, and no exception escapes.
    assert calls["n"] == 3


def test_non_object_payload_is_ignored_without_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(BASE_URL_ENV, "https://engine.example")
    monkeypatch.setenv("TECHNICAL_ENGINE_RETRIES", "2")
    calls = {"n": 0}

    def fake_get(*args: object, **kwargs: object) -> _FakeResponse:
        calls["n"] += 1
        return _FakeResponse(["not", "an", "object"])

    monkeypatch.setattr(technical_engine.httpx, "get", fake_get)
    assert technical_engine.fetch_external_technical_verdict("NVDA") is None
    # A well-formed but wrong-shaped response is a producer bug, not transient.
    assert calls["n"] == 1


def test_pulled_payload_flows_through_the_same_seam(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(BASE_URL_ENV, "https://engine.example")
    monkeypatch.setattr(technical_engine.httpx, "get", lambda *a, **k: _FakeResponse(_payload()))

    pulled = technical_engine.fetch_external_technical_verdict("NVDA")
    verdict, flags = resolve_technical_verdict(pulled)

    assert flags == []
    assert verdict is not None
    assert verdict.source is TechnicalSource.EXTERNAL
    assert verdict.direction is Direction.BUY
    # decision.v1 0-100 confidence rescaled to 0.0-1.0.
    assert verdict.confidence == pytest.approx(0.70)


def test_pulled_payload_that_violates_the_contract_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(BASE_URL_ENV, "https://engine.example")
    # SELL is illegal in an opportunity zone: the seam must reject, not accept.
    bad = _payload(action="sell")
    monkeypatch.setattr(technical_engine.httpx, "get", lambda *a, **k: _FakeResponse(bad))

    verdict, flags = resolve_technical_verdict(technical_engine.fetch_external_technical_verdict("NVDA"))
    assert verdict is None
    assert flags == ["external_technical_rejected"]
