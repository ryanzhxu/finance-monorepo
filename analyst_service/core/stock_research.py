from __future__ import annotations

import json
from datetime import date
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

from shared.config_loader import load_yaml_config

PROMPT_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "stock_research_prompt.yaml"
CONTRACT_VERSION = "stock_research_v1"


def _normalize_symbol(value: str) -> str:
    value = value.strip().upper()
    if not value:
        raise ValueError("symbol is required")
    return value


class EvidenceType(StrEnum):
    COMPANY_FILING = "company_filing"
    EARNINGS_CALL = "earnings_call"
    COMPANY_RELEASE = "company_release"
    MARKET_DATA = "market_data"
    MACRO_DATA = "macro_data"
    THIRD_PARTY_RESEARCH = "third_party_research"


class ResearchEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=240)
    url: HttpUrl
    evidence_type: EvidenceType
    published_at: date | None = None
    excerpt: str = Field(min_length=1, max_length=2_000)


class ResearchClaim(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: str = Field(min_length=1, max_length=80)
    statement: str = Field(min_length=1, max_length=1_000)
    stance: Literal["bullish", "bearish", "neutral"]
    evidence_ids: list[str] = Field(min_length=1, max_length=8)
    invalidation_condition: str = Field(min_length=1, max_length=1_000)


class ResearchPoint(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    statement: str = Field(min_length=1, max_length=1_000)
    evidence_ids: list[str] = Field(min_length=1, max_length=8)


class ResearchRisk(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    statement: str = Field(min_length=1, max_length=1_000)
    evidence_ids: list[str] = Field(default_factory=list, max_length=8)


class CandidateHypothesis(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    rank: int = Field(ge=1, le=12)
    symbol: str = Field(min_length=1, max_length=20)
    company_name: str = Field(min_length=1, max_length=240)
    thesis: str = Field(min_length=1, max_length=1_000)
    demand_driver: str = Field(min_length=1, max_length=1_000)
    evidence_ids: list[str] = Field(min_length=1, max_length=8)
    disqualifiers: list[str] = Field(min_length=1, max_length=8)

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        return _normalize_symbol(value)


class CandidateDiscoveryBrief(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    contract_version: Literal[CONTRACT_VERSION]
    as_of: date
    candidates: list[CandidateHypothesis] = Field(min_length=1, max_length=12)
    evidence: list[ResearchEvidence] = Field(min_length=1, max_length=30)
    unknowns: list[str] = Field(default_factory=list, max_length=12)

    @model_validator(mode="after")
    def validate_evidence_links(self) -> CandidateDiscoveryBrief:
        evidence_ids = [evidence.id for evidence in self.evidence]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("evidence IDs must be unique")

        ranks = sorted(candidate.rank for candidate in self.candidates)
        if ranks != list(range(1, len(self.candidates) + 1)):
            raise ValueError("candidate ranks must be unique and consecutive starting at 1")

        known_evidence_ids = set(evidence_ids)
        for candidate in self.candidates:
            missing = set(candidate.evidence_ids) - known_evidence_ids
            if missing:
                raise ValueError(
                    f"candidate {candidate.symbol} references unknown evidence IDs: {', '.join(sorted(missing))}"
                )
        return self


class StockResearchBrief(BaseModel):
    """Validated LLM decision-support output. It intentionally has no price-target field."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    contract_version: Literal[CONTRACT_VERSION]
    symbol: str = Field(min_length=1, max_length=20)
    as_of: date
    thesis: str = Field(min_length=1, max_length=2_000)
    summary: str = Field(min_length=1, max_length=2_000)
    analogy_comparison: ResearchPoint | None = None
    catalysts: list[ResearchPoint] = Field(min_length=1, max_length=8)
    entry_conditions: list[ResearchPoint] = Field(min_length=1, max_length=8)
    reasons_to_avoid: list[ResearchPoint] = Field(min_length=1, max_length=8)
    confidence: int = Field(default=0, ge=0, le=100)
    confidence_components: dict[str, int] = Field(default_factory=dict)
    evidence: list[ResearchEvidence] = Field(min_length=1, max_length=20)
    claims: list[ResearchClaim] = Field(min_length=1, max_length=12)
    risks: list[ResearchRisk] = Field(default_factory=list, max_length=12)
    unknowns: list[str] = Field(default_factory=list, max_length=12)

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        return _normalize_symbol(value)

    @model_validator(mode="after")
    def validate_evidence_links(self) -> StockResearchBrief:
        evidence_ids = [evidence.id for evidence in self.evidence]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("evidence IDs must be unique")

        known_evidence_ids = set(evidence_ids)
        for claim in self.claims:
            _validate_evidence_ids(claim.evidence_ids, known_evidence_ids, f"claim {claim.id}")
        for label, points in (
            ("analogy comparison", [self.analogy_comparison] if self.analogy_comparison else []),
            ("catalyst", self.catalysts),
            ("entry condition", self.entry_conditions),
            ("reason to avoid", self.reasons_to_avoid),
        ):
            for point in points:
                _validate_evidence_ids(point.evidence_ids, known_evidence_ids, label)
        for risk in self.risks:
            _validate_evidence_ids(risk.evidence_ids, known_evidence_ids, "risk")
        return self


class StockResearchReview(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    contract_version: Literal[CONTRACT_VERSION]
    verdict: Literal["supported", "needs_more_evidence", "reject"]
    unsupported_claim_ids: list[str] = Field(default_factory=list, max_length=12)
    missing_evidence: list[str] = Field(default_factory=list, max_length=12)
    risk_summary: str = Field(min_length=1, max_length=2_000)


class StockResearchContext(BaseModel):
    """Inputs prepared by deterministic code and a future retrieval layer."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    symbol: str = Field(min_length=1, max_length=20)
    as_of: date
    research_question: str = Field(min_length=1, max_length=1_000)
    analogy: str | None = Field(default=None, max_length=240)
    structured_analysis: dict[str, Any]
    evidence: list[ResearchEvidence] = Field(min_length=1, max_length=20)

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        return _normalize_symbol(value)


class CandidateDiscoveryContext(BaseModel):
    """Inputs for a tool-enabled discovery call, before candidates are verified."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    as_of: date
    research_question: str = Field(min_length=1, max_length=500)
    universe: str = Field(min_length=1, max_length=500)
    analogy: str | None = Field(default=None, max_length=240)
    market_context: dict[str, Any]
    max_candidates: int = Field(default=8, ge=1, le=12)


class StockResearchPromptConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    version: Literal[CONTRACT_VERSION]
    candidate_discovery_instruction: str = Field(min_length=1)
    evidence_verification_instruction: str = Field(min_length=1)
    skeptic_review_instruction: str = Field(min_length=1)


@lru_cache
def load_stock_research_prompt_config() -> StockResearchPromptConfig:
    config = load_yaml_config(
        PROMPT_CONFIG_PATH,
        {
            "version",
            "candidate_discovery_instruction",
            "evidence_verification_instruction",
            "skeptic_review_instruction",
        },
    )
    return StockResearchPromptConfig.model_validate(config)


def _json(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, default=str)


def _validate_evidence_ids(references: list[str], known_evidence_ids: set[str], label: str) -> None:
    missing = set(references) - known_evidence_ids
    if missing:
        raise ValueError(f"{label} references unknown evidence IDs: {', '.join(sorted(missing))}")


def build_candidate_discovery_prompt(context: CandidateDiscoveryContext) -> str:
    config = load_stock_research_prompt_config()
    output_schema = CandidateDiscoveryBrief.model_json_schema()
    return "\n\n".join(
        [
            config.candidate_discovery_instruction,
            f"Contract version: {config.version}",
            f"Research question: {context.research_question}",
            f"As of: {context.as_of.isoformat()}",
            f"Universe: {context.universe}",
            f"Analogy lens (comparison only): {context.analogy or 'none supplied'}",
            f"Maximum candidates: {context.max_candidates}",
            "Market context:\n" + _json(context.market_context),
            "Return JSON only. Match this schema exactly:\n" + _json(output_schema),
        ]
    )


def build_evidence_verification_prompt(context: StockResearchContext) -> str:
    config = load_stock_research_prompt_config()
    output_schema = stock_research_brief_output_schema()
    return "\n\n".join(
        [
            config.evidence_verification_instruction,
            f"Contract version: {config.version}",
            f"Research question: {context.research_question}",
            f"Symbol: {context.symbol}",
            f"As of: {context.as_of.isoformat()}",
            f"Analogy lens (comparison only): {context.analogy or 'none supplied'}",
            "Structured analysis from deterministic services:\n" + _json(context.structured_analysis),
            "Supplied evidence:\n" + _json([evidence.model_dump(mode="json") for evidence in context.evidence]),
            "Return JSON only. Match this schema exactly:\n" + _json(output_schema),
        ]
    )


def build_skeptic_review_prompt(context: StockResearchContext, brief: StockResearchBrief) -> str:
    config = load_stock_research_prompt_config()
    review_schema = StockResearchReview.model_json_schema()
    return "\n\n".join(
        [
            config.skeptic_review_instruction,
            f"Contract version: {config.version}",
            f"Analogy lens (comparison only): {context.analogy or 'none supplied'}",
            "Structured analysis:\n" + _json(context.structured_analysis),
            "Research brief to review:\n" + _json(
                brief.model_dump(mode="json", exclude={"confidence", "confidence_components"})
            ),
            "Return JSON only. Match this schema exactly:\n" + _json(review_schema),
        ]
    )


def build_stock_research_prompt(context: StockResearchContext) -> str:
    """Backward-compatible name for the evidence-verification stage."""

    return build_evidence_verification_prompt(context)


def build_stock_research_review_prompt(context: StockResearchContext, brief: StockResearchBrief) -> str:
    """Backward-compatible name for the skeptic-review stage."""

    return build_skeptic_review_prompt(context, brief)


def parse_stock_research_brief(payload: str | dict[str, Any]) -> StockResearchBrief:
    if isinstance(payload, str):
        return StockResearchBrief.model_validate_json(payload)
    return StockResearchBrief.model_validate(payload)


def stock_research_brief_output_schema() -> dict[str, Any]:
    """Keep deterministic confidence fields out of the provider's output contract."""

    schema = StockResearchBrief.model_json_schema()
    schema["properties"].pop("confidence", None)
    schema["properties"].pop("confidence_components", None)
    schema["required"] = [field for field in schema["required"] if field not in {"confidence", "confidence_components"}]
    return schema


def validate_stock_research_review(review: StockResearchReview, brief: StockResearchBrief) -> StockResearchReview:
    claim_ids = {claim.id for claim in brief.claims}
    unknown_claim_ids = set(review.unsupported_claim_ids) - claim_ids
    if unknown_claim_ids:
        raise ValueError(f"review references unknown claim IDs: {', '.join(sorted(unknown_claim_ids))}")
    return review
