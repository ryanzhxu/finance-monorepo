from __future__ import annotations

import json
import logging

from shared.models import AnalyzeResponse

from analyst_service.core.llm_client import LlmUnavailable, complete_narrative

logger = logging.getLogger(__name__)


def _narrative_prompt(response: AnalyzeResponse) -> str:
    regime = response.entry.regime if response.entry is not None and response.entry.regime is not None else response.macro.market_regime
    regime_lines = [f"Regime: {regime}"]
    if response.entry is not None and response.entry.regime_override:
        regime_lines.append(f"NOTE: Entry assessment was overridden due to {response.entry.regime} regime.")
        regime_lines.append(f"Override reason: {response.entry.regime_override_reason}")

    recommendation = response.recommendation
    if recommendation.conflict_detected and recommendation.conflict_summary:
        conflict_block = "\n".join(
            [
                f"CONFLICT: {recommendation.conflict_summary}",
                "The narrative MUST explicitly name this tension. Do not paper over it.",
                'Frame it as: "Technically [X] but fundamentally [Y]. This tension..."',
            ]
        )
    else:
        conflict_block = "No conflict between technical and fundamental signals."

    analysis_json = json.dumps(response.model_dump(mode="json", exclude={"narrative"}), indent=2)
    return (
        "You are writing a risk-control-first market analysis narrative.\n"
        "Use the structured analysis below to write 3-5 sentences.\n"
        "Rules:\n"
        "- Use only the provided structured data.\n"
        "- Do not invent numbers, catalysts, or price levels.\n"
        "- If conflict_detected is True, explicitly name the tension in the narrative — do not resolve it by picking one side.\n"
        "- If regime is risk_off, note the macro environment explicitly.\n"
        "- Narrative remains 3-5 sentences, risk-control-first tone.\n\n"
        "## Market regime\n"
        f"{chr(10).join(regime_lines)}\n\n"
        "## Signal conflict\n"
        f"{conflict_block}\n\n"
        "## Structured analysis\n"
        f"{analysis_json}"
    )


async def synthesize_narrative(response: AnalyzeResponse) -> str | None:
    prompt = _narrative_prompt(response)
    try:
        return await complete_narrative(prompt)
    except LlmUnavailable:
        return None
    except Exception as exc:
        logger.warning("Narrative synthesis failed unexpectedly: %s", exc)
        return None
