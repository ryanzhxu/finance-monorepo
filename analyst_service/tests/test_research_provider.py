from __future__ import annotations

import asyncio

import httpx
import pytest

from analyst_service.core import research_provider
from analyst_service.core.stock_research import CandidateDiscoveryBrief


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


class _CursorFakeAsyncClient:
    def __init__(self, recorder, *, run_status="FINISHED", poll_timeout=False):
        self._recorder = recorder
        self._run_status = run_status
        self._poll_timeout = poll_timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def post(self, url, headers=None, json=None):
        if url.endswith("/archive"):
            self._recorder["archive_url"] = url
            return _FakeResponse({"id": "bc-agent"})
        if url.endswith("/cancel"):
            self._recorder["cancel_url"] = url
            return _FakeResponse({"status": "CANCELLED"})
        self._recorder["create_url"] = url
        self._recorder["headers"] = headers
        self._recorder["payload"] = json
        return _FakeResponse({"agent": {"id": "bc-agent"}, "run": {"id": "run-1", "status": "RUNNING"}})

    async def get(self, url, headers=None):
        self._recorder["run_url"] = url
        if self._poll_timeout:
            raise httpx.ReadTimeout("poll timed out")
        return _FakeResponse(
            {
                "id": "run-1",
                "status": self._run_status,
                "result": '{"evidence":[{"url":"https://www.sec.gov/example"}]}',
                "usage": {"input_tokens": 10, "output_tokens": 20},
            }
        )


def test_google_research_provider_requests_grounding_and_extracts_citations(monkeypatch) -> None:
    recorder = {}
    monkeypatch.setenv("AI_RESEARCH_PROVIDER", "google")
    monkeypatch.setenv("AI_RESEARCH_API_KEY", "secret")
    monkeypatch.setenv("AI_RESEARCH_MODEL", "gemini-test")
    monkeypatch.delenv("AI_RESEARCH_BASE_URL", raising=False)
    monkeypatch.setattr(
        research_provider.httpx,
        "AsyncClient",
        lambda timeout: _FakeAsyncClient(
            payload={
                "output_text": '{"contract_version":"stock_research_v1"}',
                "steps": [
                    {
                        "type": "model_output",
                        "content": [{"annotations": [{"url": "https://www.sec.gov/example"}]}],
                    }
                ],
            },
            recorder=recorder,
        ),
    )

    completion = asyncio.run(
        research_provider.EnvironmentResearchProvider().complete("prompt", {"type": "object"}, require_web_search=True)
    )

    assert recorder["url"] == "https://generativelanguage.googleapis.com/v1beta/interactions"
    assert recorder["json"]["tools"] == [{"type": "google_search"}]
    assert completion.source_urls == frozenset({"https://www.sec.gov/example"})


def test_openai_compatible_research_provider_rejects_discovery_without_guaranteed_search(monkeypatch) -> None:
    monkeypatch.setenv("AI_RESEARCH_PROVIDER", "openai_compatible")
    monkeypatch.setenv("AI_RESEARCH_API_KEY", "secret")
    monkeypatch.setenv("AI_RESEARCH_MODEL", "model")

    try:
        asyncio.run(
            research_provider.EnvironmentResearchProvider().complete("prompt", {"type": "object"}, require_web_search=True)
        )
    except research_provider.ResearchProviderUnavailable as exc:
        assert "cannot guarantee a web-search tool" in str(exc)
    else:
        raise AssertionError("openai_compatible discovery should require a provider with web search")


def test_openai_research_provider_requests_web_search_sources(monkeypatch) -> None:
    recorder = {}
    monkeypatch.setenv("AI_RESEARCH_PROVIDER", "openai")
    monkeypatch.setenv("AI_RESEARCH_API_KEY", "secret")
    monkeypatch.setenv("AI_RESEARCH_MODEL", "gpt-test")
    monkeypatch.setattr(
        research_provider.httpx,
        "AsyncClient",
        lambda timeout: _FakeAsyncClient(
            payload={
                "output_text": '{"contract_version":"stock_research_v1"}',
                "output": [
                    {
                        "type": "web_search_call",
                        "action": {"sources": [{"url": "https://www.sec.gov/example"}]},
                    }
                ],
            },
            recorder=recorder,
        ),
    )

    completion = asyncio.run(
        research_provider.EnvironmentResearchProvider().complete("prompt", {"type": "object"}, require_web_search=True)
    )

    assert recorder["json"]["tools"] == [{"type": "web_search"}]
    assert recorder["json"]["include"] == ["web_search_call.action.sources"]
    assert completion.source_urls == frozenset({"https://www.sec.gov/example"})


def test_openai_strict_schema_requires_defaulted_pydantic_fields() -> None:
    schema = research_provider._openai_strict_schema(CandidateDiscoveryBrief.model_json_schema())

    assert schema["required"] == ["contract_version", "as_of", "candidates", "evidence", "unknowns"]
    evidence_schema = schema["$defs"]["ResearchEvidence"]
    assert evidence_schema["required"] == ["id", "title", "url", "evidence_type", "published_at", "excerpt"]
    assert "default" not in evidence_schema["properties"]["published_at"]
    assert "format" not in evidence_schema["properties"]["url"]
    assert "format" not in schema["properties"]["as_of"]


def test_cursor_provider_runs_a_no_repo_agent_with_the_stage_model(monkeypatch) -> None:
    recorder = {}
    monkeypatch.setattr(research_provider.httpx, "AsyncClient", lambda timeout: _CursorFakeAsyncClient(recorder))
    provider = research_provider.CursorCloudAgentResearchProvider(
        api_key="cursor-secret",
        models={
            "discovery": "claude-discovery",
            "verification": "claude-verification",
            "review": "claude-review",
        },
        base_url="https://cursor.example/v1",
        poll_interval_seconds=0,
    )

    completion = asyncio.run(
        provider.complete("prompt", {"type": "object"}, require_web_search=True, stage="discovery")
    )

    assert recorder["create_url"] == "https://cursor.example/v1/agents"
    assert recorder["run_url"] == "https://cursor.example/v1/agents/bc-agent/runs/run-1"
    assert recorder["archive_url"] == "https://cursor.example/v1/agents/bc-agent/archive"
    assert recorder["headers"] == {"Authorization": "Bearer cursor-secret"}
    assert recorder["payload"]["model"] == {"id": "claude-discovery"}
    assert recorder["payload"]["repos"] == []
    assert completion.grounding_mode == "agent_citations"
    assert completion.source_urls == frozenset({"https://www.sec.gov/example"})
    assert completion.model == "claude-discovery"
    assert completion.stage == "discovery"
    assert completion.agent_id == "bc-agent"
    assert completion.run_id == "run-1"
    assert completion.status == "FINISHED"
    assert completion.usage == {"input_tokens": 10, "output_tokens": 20}


def test_cursor_provider_routes_sonnet_and_haiku_by_research_stage(monkeypatch) -> None:
    recorder = {}
    monkeypatch.setattr(research_provider.httpx, "AsyncClient", lambda timeout: _CursorFakeAsyncClient(recorder))
    provider = research_provider.CursorCloudAgentResearchProvider(
        api_key="cursor-secret",
        models={
            "discovery": "claude-sonnet-5",
            "verification": "claude-haiku-4-5",
            "review": "claude-sonnet-5",
        },
        base_url="https://cursor.example/v1",
        poll_interval_seconds=0,
    )

    selected_models = []
    for stage in ("discovery", "verification", "review"):
        asyncio.run(provider.complete("", {"type": "object"}, require_web_search=False, stage=stage))
        selected_models.append(recorder["payload"]["model"]["id"])

    assert selected_models == ["claude-sonnet-5", "claude-haiku-4-5", "claude-sonnet-5"]


def test_cursor_provider_uses_a_longer_create_timeout(monkeypatch) -> None:
    recorder = {}

    def client(timeout):
        recorder["timeout"] = timeout
        return _CursorFakeAsyncClient(recorder)

    monkeypatch.setattr(
        research_provider.httpx,
        "AsyncClient",
        client,
    )
    provider = research_provider.CursorCloudAgentResearchProvider(
        api_key="cursor-secret",
        models={"discovery": "claude-haiku-4-5", "verification": "claude-haiku-4-5", "review": "claude-haiku-4-5"},
        base_url="https://cursor.example/v1",
        poll_interval_seconds=0,
        create_timeout_seconds=120,
    )

    asyncio.run(provider.complete("prompt", {"type": "object"}, require_web_search=False))

    assert recorder["timeout"] == 120


def test_cursor_provider_cancels_a_known_run_after_poll_timeout(monkeypatch) -> None:
    recorder = {}
    monkeypatch.setattr(
        research_provider.httpx,
        "AsyncClient",
        lambda timeout: _CursorFakeAsyncClient(recorder, run_status="RUNNING"),
    )
    provider = research_provider.CursorCloudAgentResearchProvider(
        api_key="cursor-secret",
        models={"discovery": "claude-haiku-4-5", "verification": "claude-haiku-4-5", "review": "claude-haiku-4-5"},
        base_url="https://cursor.example/v1",
        poll_interval_seconds=0,
        timeout_seconds=0,
    )

    with pytest.raises(research_provider.ResearchProviderUnavailable, match="cancellation requested"):
        asyncio.run(provider.complete("prompt", {"type": "object"}, require_web_search=False))

    assert recorder["cancel_url"] == "https://cursor.example/v1/agents/bc-agent/runs/run-1/cancel"


def test_cursor_provider_cancels_a_known_run_after_poll_read_timeout(monkeypatch) -> None:
    recorder = {}
    monkeypatch.setattr(
        research_provider.httpx,
        "AsyncClient",
        lambda timeout: _CursorFakeAsyncClient(recorder, poll_timeout=True),
    )
    provider = research_provider.CursorCloudAgentResearchProvider(
        api_key="cursor-secret",
        models={"discovery": "claude-haiku-4-5", "verification": "claude-haiku-4-5", "review": "claude-haiku-4-5"},
        base_url="https://cursor.example/v1",
    )

    with pytest.raises(research_provider.ResearchProviderUnavailable, match="poll timed out"):
        asyncio.run(provider.complete("prompt", {"type": "object"}, require_web_search=False))

    assert recorder["cancel_url"] == "https://cursor.example/v1/agents/bc-agent/runs/run-1/cancel"


class _CreateTimeoutAsyncClient:
    def __init__(self, recorder):
        self._recorder = recorder

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def post(self, url, headers=None, json=None):
        self._recorder["create_calls"] = self._recorder.get("create_calls", 0) + 1
        raise httpx.ReadTimeout("create timed out")


def test_cursor_provider_does_not_retry_a_create_timeout(monkeypatch) -> None:
    recorder = {}
    monkeypatch.setattr(
        research_provider.httpx,
        "AsyncClient",
        lambda timeout: _CreateTimeoutAsyncClient(recorder),
    )
    provider = research_provider.CursorCloudAgentResearchProvider(
        api_key="cursor-secret",
        models={"discovery": "claude-haiku-4-5", "verification": "claude-haiku-4-5", "review": "claude-haiku-4-5"},
        base_url="https://cursor.example/v1",
    )

    with pytest.raises(research_provider.ResearchProviderUnavailable, match="no automatic retry"):
        asyncio.run(provider.complete("prompt", {"type": "object"}, require_web_search=False))

    assert recorder["create_calls"] == 1


def test_cursor_http_error_exposes_only_bounded_provider_detail() -> None:
    request = httpx.Request("POST", "https://cursor.example/v1/agents")
    response = httpx.Response(400, request=request, json={"error": {"message": "model is unavailable"}})

    error = research_provider._cursor_http_error(httpx.HTTPStatusError("bad request", request=request, response=response))

    assert str(error) == 'Cursor agent API returned 400: {"error": {"message": "model is unavailable"}}'
