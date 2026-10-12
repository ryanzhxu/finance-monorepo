from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

from analyst_service.core.analysis import analyze_symbol
from analyst_service.core.research_provider import EnvironmentResearchProvider
from analyst_service.core.stock_research import CandidateDiscoveryContext
from analyst_service.core.stock_research_orchestrator import StockResearchOrchestrator
from shared.models import AnalyzeRequest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the grounded stock-research prompt pipeline.")
    parser.add_argument("--question", required=True)
    parser.add_argument("--universe", default="US-listed common stocks with market capitalization above USD 1 billion")
    parser.add_argument("--analogy", help="Optional comparison company or business model")
    parser.add_argument("--market-context-json", default="{}")
    parser.add_argument("--max-candidates", type=int, default=5)
    return parser.parse_args()


async def run(args: argparse.Namespace) -> dict[str, object]:
    try:
        market_context = json.loads(args.market_context_json)
    except json.JSONDecodeError as exc:
        raise SystemExit("--market-context-json must be valid JSON") from exc
    if not isinstance(market_context, dict):
        raise SystemExit("--market-context-json must contain a JSON object")

    orchestrator = StockResearchOrchestrator(EnvironmentResearchProvider())
    discovery = await orchestrator.discover(
        CandidateDiscoveryContext(
            as_of=date.today(),
            research_question=args.question,
            universe=args.universe,
            analogy=args.analogy,
            market_context=market_context,
            max_candidates=args.max_candidates,
        )
    )
    results = []
    for candidate in discovery.candidates:
        # Keep the final JSON stream machine-readable when data providers emit diagnostics.
        with contextlib.redirect_stdout(sys.stderr):
            analysis = await analyze_symbol(AnalyzeRequest(symbol=candidate.symbol, include_narrative=False))
        result = await orchestrator.research_candidate(
            candidate,
            discovery,
            analysis.model_dump(mode="json"),
            entry=analysis.entry,
            analogy=args.analogy,
        )
        results.append(
            {
                "candidate": result.candidate.model_dump(mode="json"),
                "decision_support": {
                    "candidate_rank": result.candidate.rank,
                    "analogy_comparison": result.brief.analogy_comparison.model_dump(mode="json")
                    if result.brief.analogy_comparison
                    else None,
                    "thesis": result.brief.thesis,
                    "catalysts": [item.model_dump(mode="json") for item in result.brief.catalysts],
                    "risks": [item.model_dump(mode="json") for item in result.brief.risks],
                    "entry_conditions": [item.model_dump(mode="json") for item in result.brief.entry_conditions],
                    "reasons_to_avoid": [item.model_dump(mode="json") for item in result.brief.reasons_to_avoid],
                    "deterministic_entry_assessment": result.entry.entry_assessment.value if result.entry else None,
                    "deterministic_entry_reason": result.entry.reason if result.entry else None,
                },
                "brief": result.brief.model_dump(mode="json"),
                "review": result.review.model_dump(mode="json"),
                "entry": result.entry.model_dump(mode="json") if result.entry is not None else None,
                "entry_data_freshness": {
                    "price": analysis.data_freshness.price,
                    "technicals": analysis.data_freshness.technicals,
                },
            }
        )
    return {"discovery": discovery.model_dump(mode="json"), "results": results}


def main() -> None:
    load_dotenv()
    args = parse_args()
    print(json.dumps(asyncio.run(run(args)), indent=2, default=str))


if __name__ == "__main__":
    main()
