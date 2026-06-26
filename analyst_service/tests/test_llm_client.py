from __future__ import annotations

import asyncio

import httpx

from analyst_service.core import llm_client


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self._payload


class _FakeAsyncClient:
    def __init__(self, *, payload, recorder):
        self._payload = payload
        self._recorder = recorder

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def post(self, url, headers=None, json=None):
        self._recorder["url"] = url
        self._recorder["headers"] = headers
        self._recorder["json"] = json
        return _FakeResponse(self._payload)


def test_llm_available_requires_supported_provider(monkeypatch) -> None:
    monkeypatch.setenv("AI_PROVIDER", "unsupported")
    monkeypatch.setenv("AI_API_KEY", "secret")
    monkeypatch.setenv("AI_MODEL", "model")

    assert llm_client.llm_available() is False


def test_complete_narrative_uses_google_generate_content(monkeypatch) -> None:
    recorder = {}

    monkeypatch.setenv("AI_PROVIDER", "google")
    monkeypatch.setenv("AI_API_KEY", "secret")
    monkeypatch.setenv("AI_MODEL", "gemini-2.0-flash")
    monkeypatch.delenv("AI_BASE_URL", raising=False)
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda timeout: _FakeAsyncClient(
            payload={"candidates": [{"content": {"parts": [{"text": "Structured narrative."}]}}]},
            recorder=recorder,
        ),
    )

    result = asyncio.run(llm_client.complete_narrative("Prompt text"))

    assert result == "Structured narrative."
    assert recorder["url"] == "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
    assert recorder["headers"] == {"x-goog-api-key": "secret"}
    assert recorder["json"]["contents"][0]["parts"][0]["text"] == "Prompt text"


def test_complete_narrative_uses_openai_compatible_chat_completions(monkeypatch) -> None:
    recorder = {}

    monkeypatch.setenv("AI_PROVIDER", "openai_compatible")
    monkeypatch.setenv("AI_API_KEY", "secret")
    monkeypatch.setenv("AI_MODEL", "gpt-test")
    monkeypatch.setenv("AI_BASE_URL", "https://example.com/v1")
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda timeout: _FakeAsyncClient(
            payload={"choices": [{"message": {"content": "OpenAI-compatible narrative."}}]},
            recorder=recorder,
        ),
    )

    result = asyncio.run(llm_client.complete_narrative("Prompt text"))

    assert result == "OpenAI-compatible narrative."
    assert recorder["url"] == "https://example.com/v1/chat/completions"
    assert recorder["headers"] == {"Authorization": "Bearer secret"}
    assert recorder["json"]["messages"][1]["content"] == "Prompt text"
