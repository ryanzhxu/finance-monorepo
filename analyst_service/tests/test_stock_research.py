from datetime import date

import pytest
from pydantic import ValidationError

from analyst_service.core.stock_research import (
    CONTRACT_VERSION,
    CandidateDiscoveryBrief,
    CandidateDiscoveryContext,
    ResearchEvidence,
    StockResearchBrief,
    StockResearchContext,
    StockResearchReview,
    build_candidate_discovery_prompt,
    build_evidence_verification_prompt,
    build_stock_research_prompt,
    build_stock_research_review_prompt,
    parse_stock_research_brief,
    stock_research_brief_output_schema,
    validate_stock_research_review,
)


def _evidence() -> ResearchEvidence:
    return ResearchEvidence(
        id="filing-q1",
        title="Quarterly report",
        url="https://www.sec.gov/Archives/example",
        evidence_type="company_filing",
        published_at=date(2026, 5, 1),
        excerpt="Revenue grew year over year and management raised its outlook.",
    )


def _brief() -> StockResearchBrief:
    return StockResearchBrief(
        contract_version=CONTRACT_VERSION,
        symbol="nvda",
        as_of=date(2026, 7, 11),
        thesis="Reported demand growth supports a durable growth thesis, subject to execution risk.",
        summary="The supplied filing supports a growth thesis, with material execution risk remaining.",
        analogy_comparison={
            "statement": "The evidence resembles an infrastructure-demand inflection, but does not establish a Sandisk-like outcome.",
            "evidence_ids": ["filing-q1"],
        },
        catalysts=[{"statement": "Demand growth could support continued expansion.", "evidence_ids": ["filing-q1"]}],
        entry_conditions=[{"statement": "Consider only while fresh filings continue to support demand growth.", "evidence_ids": ["filing-q1"]}],
        reasons_to_avoid=[{"statement": "Avoid if later filings show sustained contraction.", "evidence_ids": ["filing-q1"]}],
        confidence=62,
        evidence=[_evidence()],
        claims=[
            {
                "id": "growth",
                "statement": "Reported revenue growth supports the current growth thesis.",
                "stance": "bullish",
                "evidence_ids": ["filing-q1"],
                "invalidation_condition": "A later filing shows sustained revenue contraction.",
            }
        ],
        risks=[{"statement": "Execution risk remains.", "evidence_ids": ["filing-q1"]}],
        unknowns=["No point-in-time analyst estimate revision data was supplied."],
    )


def _context() -> StockResearchContext:
    return StockResearchContext(
        symbol="nvda",
        as_of=date(2026, 7, 11),
        research_question="What evidence supports or weakens the current demand-shock signal?",
        analogy="Sandisk",
        structured_analysis={"demand_shock_score": 0.81, "market_regime": "risk_on"},
        evidence=[_evidence()],
    )


def _discovery_context() -> CandidateDiscoveryContext:
    return CandidateDiscoveryContext(
        as_of=date(2026, 7, 11),
        research_question="Which listed companies could benefit from accelerating AI memory demand?",
        universe="US-listed common stocks with at least USD 1 billion market capitalization.",
        market_context={"theme": "AI infrastructure", "market_regime": "risk_on"},
        max_candidates=5,
    )


def test_brief_requires_claim_evidence_and_rejects_price_targets() -> None:
    payload = _brief().model_dump(mode="json")
    payload["claims"][0]["evidence_ids"] = ["missing-source"]

    with pytest.raises(ValidationError, match="unknown evidence IDs"):
        parse_stock_research_brief(payload)

    payload = _brief().model_dump(mode="json")
    payload["price_target"] = 999.0

    with pytest.raises(ValidationError, match="price_target"):
        parse_stock_research_brief(payload)


def test_prompt_uses_versioned_instruction_and_supplied_evidence_only() -> None:
    prompt = build_stock_research_prompt(_context())
    verification_prompt = build_evidence_verification_prompt(_context())

    assert prompt.startswith("You are an evidence-first equity research analyst.")
    assert "Use only the supplied structured analysis and evidence." in prompt
    assert '"id": "filing-q1"' in prompt
    assert CONTRACT_VERSION in prompt
    assert "price targets" in prompt
    assert "Analogy lens (comparison only): Sandisk" in prompt
    assert prompt == verification_prompt
    assert "confidence" not in stock_research_brief_output_schema()["properties"]


def test_verification_context_accepts_a_maximum_length_candidate_thesis() -> None:
    context = StockResearchContext.model_validate(
        {**_context().model_dump(mode="json"), "research_question": "x" * 1_000}
    )

    assert len(context.research_question) == 1_000


def test_candidate_discovery_prompt_requires_search_and_evidence_links() -> None:
    prompt = build_candidate_discovery_prompt(_discovery_context())

    assert prompt.startswith("You are a market research scout looking for listed companies")
    assert "Use the available web-search tools." in prompt
    assert "Maximum candidates: 5" in prompt
    assert "Analogy lens (comparison only): none supplied" in prompt
    assert "Rank candidates from 1 to N" in prompt

    payload = {
        "contract_version": CONTRACT_VERSION,
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
        "evidence": [_evidence().model_dump(mode="json")],
    }
    assert CandidateDiscoveryBrief.model_validate(payload).candidates[0].symbol == "MU"

    payload["candidates"][0]["evidence_ids"] = ["missing-source"]
    with pytest.raises(ValidationError, match="unknown evidence IDs"):
        CandidateDiscoveryBrief.model_validate(payload)


def test_decision_support_points_require_evidence_links() -> None:
    payload = _brief().model_dump(mode="json")
    payload["entry_conditions"][0]["evidence_ids"] = ["missing-source"]

    with pytest.raises(ValidationError, match="entry condition references unknown evidence IDs"):
        parse_stock_research_brief(payload)


def test_reviewer_can_only_reference_existing_claims() -> None:
    context = _context()
    brief = _brief()
    prompt = build_stock_research_review_prompt(context, brief)
    review = StockResearchReview(
        contract_version=CONTRACT_VERSION,
        verdict="needs_more_evidence",
        unsupported_claim_ids=["growth"],
        missing_evidence=["Historical estimate revisions"],
        risk_summary="The supplied filing alone does not prove persistence of growth.",
    )

    assert prompt.startswith("You are a skeptical equity research reviewer.")
    assert validate_stock_research_review(review, brief) is review

    invalid_review = review.model_copy(update={"unsupported_claim_ids": ["unknown"]})
    with pytest.raises(ValueError, match="unknown claim IDs"):
        validate_stock_research_review(invalid_review, brief)
