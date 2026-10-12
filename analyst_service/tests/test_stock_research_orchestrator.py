from __future__ import annotations

import asyncio
import json
from datetime import date

import pytest

from analyst_service.core.research_provider import ResearchCompletion
from analyst_service.core.stock_research import CandidateDiscoveryContext
from analyst_service.core.stock_research_orchestrator import (
    StockResearchOrchestrationError,
    StockResearchOrchestrator,
)
from shared.enums import EntryAssessment
from shared.models import EntryBlock


class _FakeProvider:
    def __init__(self, completions: list[ResearchCompletion]) -> None:
        self.completions = completions
        self.require_web_search: list[bool] = []
        self.stages: list[str] = []

    async def complete(self, prompt, schema, *, require_web_search, stage="discovery"):
        self.require_web_search.append(require_web_search)
        self.stages.append(stage)
        return self.completions.pop(0)


def _discovery_context() -> CandidateDiscoveryContext:
    return CandidateDiscoveryContext(
        as_of=date(2026, 7, 11),
        research_question="Find AI-memory demand-shock candidates.",
        universe="US-listed common stocks",
        market_context={"market_regime": "risk_on"},
        max_candidates=3,
    )


def _discovery_payload(source_url: str = "https://www.sec.gov/example") -> dict:
    return {
        "contract_version": "stock_research_v1",
        "as_of": "2026-07-11",
        "candidates": [
            {
                "rank": 1,
                "symbol": "MU",
                "company_name": "Micron Technology",
                "thesis": "Memory demand could accelerate.",
                "demand_driver": "AI infrastructure demand.",
                "evidence_ids": ["filing-q1"],
                "disqualifiers": ["Supply may outpace demand."],
            }
        ],
        "evidence": [
            {
                "id": "filing-q1",
                "title": "Quarterly report",
                "url": source_url,
                "evidence_type": "company_filing",
                "excerpt": "Revenue grew year over year.",
            }
        ],
    }


def _brief_payload() -> dict:
    return {
        "contract_version": "stock_research_v1",
        "symbol": "MU",
        "as_of": "2026-07-11",
        "thesis": "The evidence supports a memory-demand growth thesis, with supply risk remaining.",
        "summary": "The supplied filing supports the hypothesis, with supply risk remaining.",
        "analogy_comparison": {
            "statement": "The candidate shares a memory-demand pattern with the analogy, but outcome is unproven.",
            "evidence_ids": ["filing-q1"],
        },
        "catalysts": [{"statement": "Memory demand could accelerate.", "evidence_ids": ["filing-q1"]}],
        "entry_conditions": [{"statement": "Demand evidence must remain positive in later filings.", "evidence_ids": ["filing-q1"]}],
        "reasons_to_avoid": [{"statement": "Avoid if supply growth weakens pricing.", "evidence_ids": ["filing-q1"]}],
        "confidence": 60,
        "evidence": _discovery_payload()["evidence"],
        "claims": [
            {
                "id": "growth",
                "statement": "Reported growth supports the demand thesis.",
                "stance": "bullish",
                "evidence_ids": ["filing-q1"],
                "invalidation_condition": "A later filing reports sustained contraction.",
            }
        ],
        "risks": [{"statement": "Supply growth could weaken pricing.", "evidence_ids": ["filing-q1"]}],
    }


def _review_payload() -> dict:
    return {
        "contract_version": "stock_research_v1",
        "verdict": "needs_more_evidence",
        "unsupported_claim_ids": [],
        "missing_evidence": ["Point-in-time estimate revisions"],
        "risk_summary": "One filing does not establish durable demand growth.",
    }


def _entry(*, assessment: EntryAssessment = EntryAssessment.BUY_NOW) -> EntryBlock:
    return EntryBlock(
        current_price=101.0,
        ideal_buy_zone=(99.0, 104.0),
        aggressive_entry_price=101.0,
        conservative_entry_price=None,
        breakout_buy_level=112.5,
        support_levels=[100.0, 95.0],
        resistance_levels=[112.0, 120.0],
        stop_loss_suggestion=96.0,
        invalidation_level=94.0,
        risk_reward_ratio=2.0,
        is_overextended=False,
        breakout_volume_confirmed=False,
        entry_assessment=assessment,
        reason="Price is in the deterministic entry zone." if assessment == EntryAssessment.BUY_NOW else "Wait for a pullback.",
        regime="risk_on",
    )


def test_orchestrator_runs_grounded_discovery_then_verification_and_review() -> None:
    source_url = "https://www.sec.gov/example"
    provider = _FakeProvider(
        [
            ResearchCompletion(text=json.dumps(_discovery_payload(source_url)), source_urls=frozenset({source_url})),
            ResearchCompletion(text=json.dumps(_brief_payload()), source_urls=frozenset()),
            ResearchCompletion(text=json.dumps(_review_payload()), source_urls=frozenset()),
        ]
    )
    orchestrator = StockResearchOrchestrator(provider)

    async def run():
        discovery = await orchestrator.discover(_discovery_context())
        return await orchestrator.research_candidate(
            discovery.candidates[0],
            discovery,
            {"demand_shock_score": 0.8, "market_regime": "risk_on"},
            entry=_entry(),
        )

    result = asyncio.run(run())

    assert result.candidate.symbol == "MU"
    assert result.brief.symbol == "MU"
    assert result.brief.thesis.startswith("The evidence supports")
    assert result.brief.catalysts[0].evidence_ids == ["filing-q1"]
    assert result.brief.confidence == 53
    assert result.brief.confidence_components["total_penalty"] == 9
    assert result.review.verdict == "needs_more_evidence"
    assert result.entry is not None
    assert result.entry.entry_assessment == EntryAssessment.BUY_NOW
    assert result.entry.ideal_buy_zone == (99.0, 104.0)
    assert provider.require_web_search == [True, False, False]
    assert provider.stages == ["discovery", "verification", "review"]


def test_orchestrator_retries_invalid_json_then_rejects_ungrounded_evidence() -> None:
    provider = _FakeProvider(
        [
            ResearchCompletion(text="not json", source_urls=frozenset()),
            ResearchCompletion(
                text=json.dumps(_discovery_payload("https://www.sec.gov/example")),
                source_urls=frozenset({"https://www.sec.gov/different"}),
            ),
        ]
    )

    with pytest.raises(StockResearchOrchestrationError, match="not returned by the research provider"):
        asyncio.run(StockResearchOrchestrator(provider).discover(_discovery_context()))


def test_orchestrator_preserves_wait_entry_without_presenting_a_buy_now_signal() -> None:
    source_url = "https://www.sec.gov/example"
    provider = _FakeProvider(
        [
            ResearchCompletion(text=json.dumps(_discovery_payload(source_url)), source_urls=frozenset({source_url})),
            ResearchCompletion(text=json.dumps(_brief_payload()), source_urls=frozenset()),
            ResearchCompletion(text=json.dumps(_review_payload()), source_urls=frozenset()),
        ]
    )
    entry = _entry(assessment=EntryAssessment.WAIT_FOR_PULLBACK)
    entry = entry.model_copy(update={"aggressive_entry_price": None, "conservative_entry_price": 99.0})

    async def run():
        orchestrator = StockResearchOrchestrator(provider)
        discovery = await orchestrator.discover(_discovery_context())
        return await orchestrator.research_candidate(
            discovery.candidates[0],
            discovery,
            {"demand_shock_score": 0.8, "market_regime": "risk_on"},
            entry=entry,
        )

    result = asyncio.run(run())

    assert result.entry is not None
    assert result.entry.entry_assessment == EntryAssessment.WAIT_FOR_PULLBACK
    assert result.entry.aggressive_entry_price is None
    assert result.entry.conservative_entry_price == 99.0


def test_orchestrator_stops_when_provider_attempt_budget_is_exhausted() -> None:
    provider = _FakeProvider([ResearchCompletion(text="not json", source_urls=frozenset())])

    with pytest.raises(StockResearchOrchestrationError, match="attempt budget exhausted"):
        asyncio.run(
            StockResearchOrchestrator(
                provider,
                max_attempts=2,
                max_provider_attempts=1,
            ).discover(_discovery_context())
        )
