from __future__ import annotations

import os
from typing import Any

import httpx


class LlmUnavailable(RuntimeError):
    pass


SUPPORTED_PROVIDERS = {"openai_compatible", "google"}


def llm_available() -> bool:
    provider = os.getenv("AI_PROVIDER")
    return bool(provider in SUPPORTED_PROVIDERS and os.getenv("AI_API_KEY") and os.getenv("AI_MODEL"))


def _extract_openai_compatible_text(data: dict[str, Any]) -> str:
    return str(data["choices"][0]["message"]["content"]).strip()


def _extract_google_text(data: dict[str, Any]) -> str:
    candidates = data.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise LlmUnavailable("Google narrative response did not include candidates")
    content = candidates[0].get("content")
    if not isinstance(content, dict):
        raise LlmUnavailable("Google narrative response did not include content")
    parts = content.get("parts")
    if not isinstance(parts, list) or not parts:
        raise LlmUnavailable("Google narrative response did not include parts")
    text_chunks = [part.get("text") for part in parts if isinstance(part, dict) and isinstance(part.get("text"), str)]
    text = "\n".join(chunk.strip() for chunk in text_chunks if chunk.strip()).strip()
    if not text:
        raise LlmUnavailable("Google narrative response did not include text")
    return text


async def complete_narrative(prompt: str) -> str:
    provider = os.getenv("AI_PROVIDER")
    api_key = os.getenv("AI_API_KEY")
    model = os.getenv("AI_MODEL")
    base_url = os.getenv("AI_BASE_URL")
    if not (provider and api_key and model):
        raise LlmUnavailable("AI_PROVIDER, AI_API_KEY, and AI_MODEL are required for narrative synthesis")
    if provider not in SUPPORTED_PROVIDERS:
        raise LlmUnavailable(f"Unsupported AI_PROVIDER: {provider}")
    if provider == "openai_compatible":
        url = (base_url or "https://api.openai.com/v1").rstrip("/") + "/chat/completions"
        headers = {"Authorization": f"Bearer {api_key}"}
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": "Explain the structured stock analysis. Do not introduce new numbers."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
        }
        extractor = _extract_openai_compatible_text
    else:
        url = (
            base_url or "https://generativelanguage.googleapis.com/v1beta"
        ).rstrip("/") + f"/models/{model}:generateContent"
        headers = {"x-goog-api-key": api_key}
        payload = {
            "system_instruction": {
                "parts": [
                    {"text": "Explain the structured stock analysis. Do not introduce new numbers."}
                ]
            },
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": prompt}],
                }
            ],
            "generationConfig": {"temperature": 0.2},
        }
        extractor = _extract_google_text
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
        data = response.json()
        return extractor(data)
    except httpx.HTTPError as exc:
        raise LlmUnavailable(f"Narrative provider request failed: {type(exc).__name__}") from exc
    except ValueError as exc:
        raise LlmUnavailable("Narrative provider returned invalid JSON") from exc
