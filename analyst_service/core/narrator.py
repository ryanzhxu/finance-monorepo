from __future__ import annotations

import json

from shared.models import AnalyzeResponse

from analyst_service.core.llm_client import LlmUnavailable, complete_narrative


async def synthesize_narrative(response: AnalyzeResponse) -> str | None:
    prompt = json.dumps(response.model_dump(mode="json", exclude={"narrative"}), indent=2)
    try:
        return await complete_narrative(prompt)
    except LlmUnavailable:
        return None
