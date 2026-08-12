from __future__ import annotations

import asyncio
import json
import os
import time
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Literal, Protocol

import httpx


class ResearchProviderUnavailable(RuntimeError):
    pass


ResearchStage = Literal["discovery", "verification", "review"]


@dataclass(frozen=True)
class ResearchCompletion:
    text: str
    source_urls: frozenset[str]
    grounding_mode: Literal["provider_metadata", "agent_citations"] = "provider_metadata"
    model: str | None = None
    stage: ResearchStage | None = None
    agent_id: str | None = None
    run_id: str | None = None
    status: str | None = None
    elapsed_seconds: float | None = None
    usage: dict[str, Any] | None = None


class StructuredResearchProvider(Protocol):
    async def complete(
        self,
        prompt: str,
        schema: dict[str, Any],
        *,
        require_web_search: bool,
        stage: ResearchStage = "discovery",
    ) -> ResearchCompletion: ...


def research_provider_available() -> bool:
    provider = os.getenv("AI_RESEARCH_PROVIDER") or os.getenv("AI_PROVIDER")
    if provider == "cursor":
        return bool(os.getenv("CURSOR_API_KEY") and all(_cursor_model(stage) for stage in _RESEARCH_STAGES))
    api_key = os.getenv("AI_RESEARCH_API_KEY") or os.getenv("AI_API_KEY")
    model = os.getenv("AI_RESEARCH_MODEL") or os.getenv("AI_MODEL")
    return bool(provider in {"google", "openai", "openai_compatible"} and api_key and model)


_RESEARCH_STAGES: tuple[ResearchStage, ...] = ("discovery", "verification", "review")


def _cursor_model(stage: ResearchStage) -> str | None:
    return os.getenv(f"CURSOR_RESEARCH_{stage.upper()}_MODEL")


def _settings(stage: ResearchStage) -> tuple[str, str, str, str | None]:
    provider = os.getenv("AI_RESEARCH_PROVIDER") or os.getenv("AI_PROVIDER")
    api_key = os.getenv("AI_RESEARCH_API_KEY") or os.getenv("AI_API_KEY")
    model = os.getenv(f"AI_RESEARCH_{stage.upper()}_MODEL") or os.getenv("AI_RESEARCH_MODEL") or os.getenv("AI_MODEL")
    base_url = os.getenv("AI_RESEARCH_BASE_URL") or os.getenv("AI_BASE_URL")
    if not (provider and api_key and model):
        raise ResearchProviderUnavailable(
            "AI_RESEARCH_PROVIDER, AI_RESEARCH_API_KEY, and AI_RESEARCH_MODEL are required "
            "(AI_PROVIDER, AI_API_KEY, and AI_MODEL are accepted as fallbacks)"
        )
    if provider not in {"google", "openai", "openai_compatible"}:
        raise ResearchProviderUnavailable(f"Unsupported research provider: {provider}")
    return provider, api_key, model, base_url


def _extract_text(data: dict[str, Any]) -> str:
    output_text = data.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    texts: list[str] = []

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            text = value.get("text")
            if isinstance(text, str) and text.strip():
                texts.append(text.strip())
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(data.get("output") or data.get("steps") or data.get("candidates"))
    if not texts:
        raise ResearchProviderUnavailable("Research provider response did not include text")
    return "\n".join(dict.fromkeys(texts))


def _extract_source_urls(data: dict[str, Any]) -> frozenset[str]:
    urls: set[str] = set()

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            url = value.get("url")
            if isinstance(url, str) and url.startswith(("https://", "http://")):
                urls.add(url.rstrip("/"))
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(data)
    return frozenset(urls)


def _safe_metadata(value: Any, *, depth: int = 0) -> Any:
    """Keep provider metadata JSON-safe without copying arbitrary response objects."""

    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if depth >= 4:
        return None
    if isinstance(value, dict):
        return {str(key): _safe_metadata(item, depth=depth + 1) for key, item in value.items()}
    if isinstance(value, list):
        return [_safe_metadata(item, depth=depth + 1) for item in value]
    return None


def _safe_usage(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return _safe_metadata(value)


def _openai_strict_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Make Pydantic's optional defaults valid for OpenAI strict JSON output."""

    normalized = deepcopy(schema)

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            # Pydantic emits URI/date formats that OpenAI strict mode does not accept.
            # The Pydantic model still validates those formats after completion.
            value.pop("format", None)
            properties = value.get("properties")
            if isinstance(properties, dict):
                # OpenAI strict mode requires every object property to be required.
                value["required"] = list(properties)
                for property_schema in properties.values():
                    if isinstance(property_schema, dict):
                        property_schema.pop("default", None)
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(normalized)
    return normalized


def _cursor_agent_prompt(prompt: str, schema: dict[str, Any], *, require_web_search: bool) -> str:
    research_instruction = (
        "Use public web research before answering and cite every source URL in the JSON evidence."
        if require_web_search
        else "Do not browse or add facts beyond the supplied prompt and evidence."
    )
    return "\n\n".join(
        [
            "You are a no-repo equity research agent. "
            "Do not modify files, run package installs, create commits, create pull requests, or use any repository context.",
            research_instruction,
            "Your entire final response must be valid JSON only, with no Markdown fence or commentary.",
            prompt,
            "Provider response schema:\n" + json.dumps(schema, sort_keys=True),
        ]
    )


def _cursor_result_json(text: str) -> str:
    text = text.strip()
    if text.startswith("```") and text.endswith("```"):
        text = text.split("\n", 1)[1].rsplit("\n", 1)[0].strip()
    try:
        json.loads(text)
    except ValueError as exc:
        raise ResearchProviderUnavailable("Cursor agent final result was not valid JSON") from exc
    return text


def _cursor_http_error(exc: httpx.HTTPStatusError) -> ResearchProviderUnavailable:
    """Expose Cursor's bounded error detail without leaking request credentials."""

    response = exc.response
    try:
        detail = json.dumps(response.json(), sort_keys=True)
    except ValueError:
        detail = response.text.strip()
    detail = detail[:500] or "no response detail"
    return ResearchProviderUnavailable(f"Cursor agent API returned {response.status_code}: {detail}")


class CursorCloudAgentResearchProvider:
    """Run each research stage as a no-repo Cursor Cloud Agent."""

    def __init__(
        self,
        *,
        api_key: str,
        models: dict[ResearchStage, str],
        base_url: str = "https://api.cursor.com/v1",
        poll_interval_seconds: float = 2.0,
        timeout_seconds: float = 300.0,
        create_timeout_seconds: float = 120.0,
    ) -> None:
        self._api_key = api_key
        self._models = models
        self._base_url = base_url.rstrip("/")
        self._poll_interval_seconds = poll_interval_seconds
        self._timeout_seconds = timeout_seconds
        self._create_timeout_seconds = create_timeout_seconds

    async def complete(
        self,
        prompt: str,
        schema: dict[str, Any],
        *,
        require_web_search: bool,
        stage: ResearchStage = "discovery",
    ) -> ResearchCompletion:
        payload = {
            "prompt": {"text": _cursor_agent_prompt(prompt, schema, require_web_search=require_web_search)},
            "model": {"id": self._models[stage]},
            "repos": [],
            "mode": "agent",
        }
        headers = {"Authorization": f"Bearer {self._api_key}"}
        started_at = time.monotonic()
        agent_id: str | None = None
        run_id: str | None = None
        try:
            async with httpx.AsyncClient(timeout=self._create_timeout_seconds) as client:
                try:
                    create_response = await client.post(f"{self._base_url}/agents", headers=headers, json=payload)
                    create_response.raise_for_status()
                    created = create_response.json()
                    agent_id = str(created["agent"]["id"])
                    run_id = str(created["run"]["id"])
                    deadline = time.monotonic() + self._timeout_seconds
                    while time.monotonic() < deadline:
                        run_response = await client.get(
                            f"{self._base_url}/agents/{agent_id}/runs/{run_id}",
                            headers=headers,
                        )
                        run_response.raise_for_status()
                        run = run_response.json()
                        status = run.get("status")
                        if status == "FINISHED":
                            result = run.get("result")
                            if not isinstance(result, str) or not result.strip():
                                raise ResearchProviderUnavailable("Cursor agent finished without a final result")
                            text = _cursor_result_json(result)
                            source_urls = _extract_source_urls(json.loads(text)) if require_web_search else frozenset()
                            # Keep the completed run readable in Cursor while avoiding a growing active-agent list.
                            try:
                                archive_response = await client.post(
                                    f"{self._base_url}/agents/{agent_id}/archive",
                                    headers=headers,
                                )
                                archive_response.raise_for_status()
                            except httpx.HTTPError:
                                pass
                            return ResearchCompletion(
                                text=text,
                                source_urls=source_urls,
                                grounding_mode="agent_citations",
                                model=self._models[stage],
                                stage=stage,
                                agent_id=agent_id,
                                run_id=run_id,
                                status=str(status),
                                elapsed_seconds=round(time.monotonic() - started_at, 3),
                                usage=_safe_usage(run.get("usage")),
                            )
                        if status in {"ERROR", "CANCELLED", "EXPIRED"}:
                            raise ResearchProviderUnavailable(f"Cursor agent ended with status: {status}")
                        await asyncio.sleep(self._poll_interval_seconds)

                    cancellation_requested = await self._cancel_run(client, headers, agent_id, run_id)
                    cancellation_note = "cancellation requested" if cancellation_requested else "cancellation request failed"
                    raise ResearchProviderUnavailable(
                        f"Cursor agent timed out after {self._timeout_seconds:.1f}s; {cancellation_note}; do not retry automatically"
                    )
                except asyncio.CancelledError:
                    if agent_id and run_id:
                        await self._cancel_run(client, headers, agent_id, run_id)
                    raise
                except httpx.ReadTimeout as exc:
                    if agent_id and run_id:
                        cancellation_requested = await self._cancel_run(client, headers, agent_id, run_id)
                        cancellation_note = "cancellation requested" if cancellation_requested else "cancellation request failed"
                        raise ResearchProviderUnavailable(
                            f"Cursor agent poll timed out after run creation; {cancellation_note}; do not retry automatically"
                        ) from exc
                    raise
        except httpx.HTTPStatusError as exc:
            raise _cursor_http_error(exc) from exc
        except httpx.ReadTimeout as exc:
            raise ResearchProviderUnavailable(
                "Cursor agent request timed out; no automatic retry was attempted. Check the provider run status before retrying."
            ) from exc
        except (httpx.HTTPError, KeyError, TypeError) as exc:
            raise ResearchProviderUnavailable(f"Cursor agent request failed: {type(exc).__name__}") from exc

    async def _cancel_run(
        self,
        client: httpx.AsyncClient,
        headers: dict[str, str],
        agent_id: str,
        run_id: str,
    ) -> bool:
        try:
            response = await client.post(
                f"{self._base_url}/agents/{agent_id}/runs/{run_id}/cancel",
                headers=headers,
            )
            response.raise_for_status()
            return True
        except httpx.HTTPError:
            return False


def _cursor_provider() -> CursorCloudAgentResearchProvider:
    api_key = os.getenv("CURSOR_API_KEY")
    models = {stage: _cursor_model(stage) for stage in _RESEARCH_STAGES}
    if not api_key or not all(models.values()):
        raise ResearchProviderUnavailable(
            "CURSOR_API_KEY plus CURSOR_RESEARCH_DISCOVERY_MODEL, CURSOR_RESEARCH_VERIFICATION_MODEL, "
            "and CURSOR_RESEARCH_REVIEW_MODEL are required"
        )
    return CursorCloudAgentResearchProvider(
        api_key=api_key,
        models={stage: model for stage, model in models.items() if model is not None},
        base_url=os.getenv("CURSOR_API_BASE_URL") or "https://api.cursor.com/v1",
    )


async def list_cursor_models() -> dict[str, Any]:
    api_key = os.getenv("CURSOR_API_KEY")
    if not api_key:
        raise ResearchProviderUnavailable("CURSOR_API_KEY is required")
    base_url = (os.getenv("CURSOR_API_BASE_URL") or "https://api.cursor.com/v1").rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=45) as client:
            response = await client.get(f"{base_url}/models", headers={"Authorization": f"Bearer {api_key}"})
            response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise ResearchProviderUnavailable(f"Cursor model listing failed: {type(exc).__name__}") from exc


class EnvironmentResearchProvider:
    """Calls a configured provider without exposing credentials to prompts or output."""

    async def complete(
        self,
        prompt: str,
        schema: dict[str, Any],
        *,
        require_web_search: bool,
        stage: ResearchStage = "discovery",
    ) -> ResearchCompletion:
        provider = os.getenv("AI_RESEARCH_PROVIDER") or os.getenv("AI_PROVIDER")
        if provider == "cursor":
            return await _cursor_provider().complete(
                prompt,
                schema,
                require_web_search=require_web_search,
                stage=stage,
            )

        started_at = time.monotonic()
        provider, api_key, model, base_url = _settings(stage)
        if require_web_search and provider == "openai_compatible":
            raise ResearchProviderUnavailable(
                "openai_compatible cannot guarantee a web-search tool; use google or openai for candidate discovery"
            )

        if provider == "google":
            url = (base_url or "https://generativelanguage.googleapis.com/v1beta").rstrip("/") + "/interactions"
            headers = {"x-goog-api-key": api_key}
            payload: dict[str, Any] = {"model": model, "input": prompt}
            if require_web_search:
                payload["tools"] = [{"type": "google_search"}]
        elif provider == "openai":
            url = (base_url or "https://api.openai.com/v1").rstrip("/") + "/responses"
            headers = {"Authorization": f"Bearer {api_key}"}
            payload = {
                "model": model,
                "input": prompt,
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": "stock_research",
                        "strict": True,
                        "schema": _openai_strict_schema(schema),
                    }
                },
            }
            if require_web_search:
                payload["tools"] = [{"type": "web_search"}]
                # Source URLs are omitted from Responses output unless explicitly requested.
                payload["include"] = ["web_search_call.action.sources"]
        else:
            url = (base_url or "https://api.openai.com/v1").rstrip("/") + "/chat/completions"
            headers = {"Authorization": f"Bearer {api_key}"}
            payload = {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "response_format": {"type": "json_object"},
                "temperature": 0.1,
            }

        try:
            async with httpx.AsyncClient(timeout=45) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
            data = response.json()
        except httpx.HTTPError as exc:
            raise ResearchProviderUnavailable(f"Research provider request failed: {type(exc).__name__}") from exc
        except ValueError as exc:
            raise ResearchProviderUnavailable("Research provider returned invalid JSON") from exc

        if provider == "openai_compatible":
            try:
                text = str(data["choices"][0]["message"]["content"]).strip()
            except (IndexError, KeyError, TypeError) as exc:
                raise ResearchProviderUnavailable("Research provider response did not include a completion") from exc
        else:
            text = _extract_text(data)
        if not text:
            raise ResearchProviderUnavailable("Research provider returned an empty completion")
        return ResearchCompletion(
            text=text,
            source_urls=_extract_source_urls(data),
            model=model,
            stage=stage,
            status="completed",
            elapsed_seconds=round(time.monotonic() - started_at, 3),
            usage=_safe_usage(data.get("usage") or data.get("usageMetadata")),
        )
