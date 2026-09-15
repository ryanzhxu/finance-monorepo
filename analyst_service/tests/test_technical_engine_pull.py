from __future__ import annotations

import httpx
import pytest

from shared.enums import Direction, Horizon, TechnicalSource

from analyst_service.core.provider_clients import technical_engine
from analyst_service.core.technical_provider import resolve_technical_verdict

BASE_URL_ENV = "TECHNICAL_ENGINE_BASE_URL"


def _horizon_verdict(**overrides: object) -> dict[str, object]:
    verdict: dict[str, object] = {
        "action": "buy",
        "confidence": 70,
        "priceState": "IN_OPPORTUNITY_ZONE",
        "executionIntent": "enter",
        "opportunityRange": {"low": 100.0, "high": 110.0},
        "reduceRange": {"low": 140.0, "high": 150.0},
        "invalidation": 95.0,
        "currentPrice": 105.0,
        "reasons": ["Weekly trend intact"],
        "dataQuality": 88,
    }
    verdict.update(overrides)
    return verdict


def _envelope(**horizon_overrides: dict[str, object]) -> dict[str, object]:
    """Vincent's real `GET /decision/<ticker>` shape: all horizons in one call."""
    horizons = {
        "short": _horizon_verdict(),
        "mid": _horizon_verdict(),
        "long": _horizon_verdict(),
    }
    for key, overrides in horizon_overrides.items():
        horizons[key] = _horizon_verdict(**overrides)
    return {
        "contractVersion": "decision.v1",
        "producer": "vincent-stock-decision-dashboard",
        "ticker": "NVDA",
        "generatedAt": "2026-09-14T00:00:00Z",
        "currentPrice": 105.0,
        "horizons": horizons,
    }


class _FakeResponse:
    def __init__(self, payload: object, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=self)  # type: ignore[arg-type]

    def json(self) -> object:
        return self._payload


def test_off_by_default_returns_none_without_calling_out(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(BASE_URL_ENV, raising=False)

    def forbidden(*args: object, **kwargs: object) -> object:
        raise AssertionError("pull must not touch the network when off")

    monkeypatch.setattr(technical_engine.httpx, "get", forbidden)
    assert technical_engine.fetch_external_technical_verdict("NVDA", Horizon.TWO_TO_FOUR_WEEKS) is None


def test_pulls_the_envelope_once_with_no_horizon_param(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(BASE_URL_ENV, "https://engine.example/api/")
    captured: dict[str, object] = {}

    def fake_get(url: str, timeout: float) -> _FakeResponse:
        captured["url"] = url
        captured["timeout"] = timeout
        return _FakeResponse(_envelope())

    monkeypatch.setattr(technical_engine.httpx, "get", fake_get)
    result = technical_engine.fetch_external_technical_verdict("nvda", Horizon.TWO_TO_FOUR_WEEKS)

    assert isinstance(result, dict)
    # mid == 2-4W
    assert result["action"] == "buy"
    assert result["producer"] == "vincent-stock-decision-dashboard"
    # Trailing slash trimmed, symbol upper-cased. Vincent's endpoint ignores any
    # horizon query param and always returns all three, so none is sent.
    assert captured["url"] == "https://engine.example/api/decision/NVDA"


def test_horizon_maps_to_vincents_short_mid_long_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(BASE_URL_ENV, "https://engine.example")
    envelope = _envelope(short={"action": "hold"}, mid={"action": "buy"}, long={"action": "sell", "priceState": "IN_REDUCE_ZONE"})
    monkeypatch.setattr(technical_engine.httpx, "get", lambda *a, **k: _FakeResponse(envelope))

    assert technical_engine.fetch_external_technical_verdict("NVDA", Horizon.ONE_WEEK)["action"] == "hold"
    assert technical_engine.fetch_external_technical_verdict("NVDA", Horizon.TWO_TO_FOUR_WEEKS)["action"] == "buy"
    assert technical_engine.fetch_external_technical_verdict("NVDA", Horizon.THREE_TO_SIX_MONTHS)["action"] == "sell"


def test_horizon_with_no_counterpart_skips_the_network_call(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(BASE_URL_ENV, "https://engine.example")

    def forbidden(*args: object, **kwargs: object) -> object:
        raise AssertionError("a horizon with no decision.v1 counterpart must not call out")

    monkeypatch.setattr(technical_engine.httpx, "get", forbidden)
    assert technical_engine.fetch_external_technical_verdict("NVDA", Horizon.ONE_DAY) is None


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


def test_success_false_body_is_treated_as_no_verdict(monkeypatch: pytest.MonkeyPatch) -> None:
    """A ticker the engine declined comes back HTTP 200 with success: false."""
    monkeypatch.setenv(BASE_URL_ENV, "https://engine.example")
    monkeypatch.setattr(
        technical_engine.httpx,
        "get",
        lambda *a, **k: _FakeResponse({"success": False, "error": "no decision for NVDA"}),
    )
    assert technical_engine.fetch_external_technical_verdict("NVDA") is None


def test_404_for_unknown_ticker_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(BASE_URL_ENV, "https://engine.example")
    monkeypatch.setattr(
        technical_engine.httpx,
        "get",
        lambda *a, **k: _FakeResponse({"success": False, "error": "no cached quote"}, status_code=404),
    )
    assert technical_engine.fetch_external_technical_verdict("ZZZZ") is None


def test_pulled_payload_flows_through_the_same_seam(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(BASE_URL_ENV, "https://engine.example")
    monkeypatch.setattr(technical_engine.httpx, "get", lambda *a, **k: _FakeResponse(_envelope()))

    pulled = technical_engine.fetch_external_technical_verdict("NVDA", Horizon.TWO_TO_FOUR_WEEKS)
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
    bad = _envelope(mid={"action": "sell"})
    monkeypatch.setattr(technical_engine.httpx, "get", lambda *a, **k: _FakeResponse(bad))

    pulled = technical_engine.fetch_external_technical_verdict("NVDA", Horizon.TWO_TO_FOUR_WEEKS)
    verdict, flags = resolve_technical_verdict(pulled)
    assert verdict is None
    assert flags == ["external_technical_rejected"]


def test_a_decimal_retries_value_falls_back_to_the_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(BASE_URL_ENV, "https://engine.example")
    # int("3.0") raises ValueError in Python, unlike JS's Number("3.0"), so this
    # must fall back to the default (1 retry) rather than silently using 3.
    monkeypatch.setenv("TECHNICAL_ENGINE_RETRIES", "3.0")
    calls = {"n": 0}

    def failing_get(*args: object, **kwargs: object) -> object:
        calls["n"] += 1
        raise httpx.HTTPError("boom")

    monkeypatch.setattr(technical_engine.httpx, "get", failing_get)
    assert technical_engine.fetch_external_technical_verdict("NVDA") is None
    assert calls["n"] == 2


def test_fetch_verdicts_by_horizon_makes_exactly_one_call(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(BASE_URL_ENV, "https://engine.example")
    calls = {"n": 0}

    def fake_get(url: str, timeout: float) -> _FakeResponse:
        calls["n"] += 1
        return _FakeResponse(_envelope())

    monkeypatch.setattr(technical_engine.httpx, "get", fake_get)
    horizons = [Horizon.ONE_WEEK, Horizon.TWO_TO_FOUR_WEEKS, Horizon.THREE_TO_SIX_MONTHS]

    result = technical_engine.fetch_external_technical_verdicts("NVDA", horizons)

    # Vincent's engine returns all three horizons in one response.
    assert calls["n"] == 1
    assert set(result.keys()) == set(horizons)


def test_fetch_verdicts_by_horizon_skips_a_horizon_missing_from_the_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(BASE_URL_ENV, "https://engine.example")
    envelope = _envelope()
    del envelope["horizons"]["long"]  # type: ignore[index]
    monkeypatch.setattr(technical_engine.httpx, "get", lambda *a, **k: _FakeResponse(envelope))
    horizons = [Horizon.ONE_WEEK, Horizon.TWO_TO_FOUR_WEEKS, Horizon.THREE_TO_SIX_MONTHS]

    result = technical_engine.fetch_external_technical_verdicts("NVDA", horizons)

    assert set(result.keys()) == {Horizon.ONE_WEEK, Horizon.TWO_TO_FOUR_WEEKS}


def test_fetch_verdicts_by_horizon_returns_empty_dict_when_pull_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(BASE_URL_ENV, "https://engine.example")

    def failing_get(*args: object, **kwargs: object) -> object:
        raise httpx.HTTPError("boom")

    monkeypatch.setattr(technical_engine.httpx, "get", failing_get)
    horizons = [Horizon.ONE_WEEK, Horizon.TWO_TO_FOUR_WEEKS, Horizon.THREE_TO_SIX_MONTHS]

    assert technical_engine.fetch_external_technical_verdicts("NVDA", horizons) == {}
