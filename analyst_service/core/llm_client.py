from __future__ import annotations

import os

import httpx


class LlmUnavailable(RuntimeError):
    pass


def llm_available() -> bool:
    return bool(os.getenv("AI_PROVIDER") and os.getenv("AI_API_KEY") and os.getenv("AI_MODEL"))


async def complete_narrative(prompt: str) -> str:
    provider = os.getenv("AI_PROVIDER")
    api_key = os.getenv("AI_API_KEY")
    model = os.getenv("AI_MODEL")
    base_url = os.getenv("AI_BASE_URL")
    if not (provider and api_key and model):
        raise LlmUnavailable("AI_PROVIDER, AI_API_KEY, and AI_MODEL are required for narrative synthesis")
    if provider != "openai_compatible":
        raise LlmUnavailable(f"Unsupported AI_PROVIDER: {provider}")
    url = (base_url or "https://api.openai.com/v1").rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "Explain the structured stock analysis. Do not introduce new numbers."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
    }
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(url, headers={"Authorization": f"Bearer {api_key}"}, json=payload)
        response.raise_for_status()
    data = response.json()
    return str(data["choices"][0]["message"]["content"]).strip()
