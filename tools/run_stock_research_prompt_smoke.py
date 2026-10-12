from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analyst_service.core.research_provider import CursorCloudAgentResearchProvider, ResearchProviderUnavailable
from analyst_service.core.stock_research import CandidateDiscoveryContext
from analyst_service.core.stock_research_orchestrator import StockResearchOrchestrator

CHEAPEST_KNOWN_CURSOR_MODEL = "claude-haiku-4-5"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the stock-research prompt contract smoke with the cheapest known model")
    parser.add_argument(
        "--question",
        default="Find one US-listed company with a verifiable AI-infrastructure or memory-demand inflection.",
    )
    parser.add_argument("--universe", default="US-listed common stocks")
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def build_provider() -> CursorCloudAgentResearchProvider:
    api_key = os.getenv("CURSOR_API_KEY")
    if not api_key:
        raise ResearchProviderUnavailable("CURSOR_API_KEY is required for the live prompt smoke")
    return CursorCloudAgentResearchProvider(
        api_key=api_key,
        models={
            "discovery": CHEAPEST_KNOWN_CURSOR_MODEL,
            "verification": CHEAPEST_KNOWN_CURSOR_MODEL,
            "review": CHEAPEST_KNOWN_CURSOR_MODEL,
        },
        base_url=os.getenv("CURSOR_API_BASE_URL") or "https://api.cursor.com/v1",
    )


async def run_smoke(question: str, universe: str) -> dict[str, object]:
    # Keep the approved smoke deterministic: one provider attempt per stage and one candidate.
    orchestrator = StockResearchOrchestrator(build_provider(), max_attempts=1, max_provider_attempts=3)
    discovery = await orchestrator.discover(
        CandidateDiscoveryContext(
            as_of=date.today(),
            research_question=question,
            universe=universe,
            market_context={"smoke_test": True},
            max_candidates=1,
        )
    )
    candidate = discovery.candidates[0]
    result = await orchestrator.research_candidate(
        candidate,
        discovery,
        {"smoke_test": True, "forecast_status": "unavailable"},
    )
    provider_runs = [
        {
            "stage": completion.stage,
            "model": completion.model,
            "agent_id": completion.agent_id,
            "run_id": completion.run_id,
            "status": completion.status,
            "elapsed_seconds": completion.elapsed_seconds,
            "usage": completion.usage,
            "usage_available": completion.usage is not None,
        }
        for completion in orchestrator.provider_completions
    ]
    return {
        "model": CHEAPEST_KNOWN_CURSOR_MODEL,
        "provider_runs": provider_runs,
        "discovery_contract": "valid",
        "discovery_candidate_count": len(discovery.candidates),
        "discovery_symbol": candidate.symbol,
        "verification_contract": "valid",
        "review_contract": "valid",
        "review_verdict": result.review.verdict,
        "numeric_forecast": "unavailable",
    }


def main() -> int:
    load_dotenv()
    args = parse_args()
    report = asyncio.run(run_smoke(args.question, args.universe))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
