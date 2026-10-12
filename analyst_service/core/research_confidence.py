from __future__ import annotations

from datetime import date
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field

from shared.config_loader import load_yaml_config, require_nested_keys

from analyst_service.core.stock_research import EvidenceType, StockResearchBrief, StockResearchReview

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "stock_research_confidence.yaml"


class ResearchConfidenceComponents(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_quality: int = Field(ge=0, le=100)
    evidence_breadth: int = Field(ge=0, le=100)
    source_diversity: int = Field(ge=0, le=100)
    evidence_recency: int = Field(ge=0, le=100)
    base_score: int = Field(ge=0, le=100)
    total_penalty: int = Field(ge=0, le=100)
    score: int = Field(ge=0, le=100)


@lru_cache
def load_research_confidence_config() -> dict:
    config = load_yaml_config(CONFIG_PATH, {"evidence_quality", "weights", "thresholds", "penalties"})
    require_nested_keys(
        config,
        {
            "weights": {"evidence_quality", "evidence_breadth", "source_diversity", "evidence_recency"},
            "thresholds": {
                "target_evidence_count",
                "target_source_domains",
                "fresh_within_days",
                "stale_after_days",
                "missing_publication_date_score",
            },
            "penalties": {
                "unsupported_claim",
                "missing_evidence",
                "unresolved_unknown",
                "needs_more_evidence_verdict",
                "reject_verdict",
                "maximum_total",
            },
        },
        "stock research confidence config",
    )
    missing_types = {item.value for item in EvidenceType} - set(config["evidence_quality"])
    if missing_types:
        raise ValueError("stock research confidence config missing evidence types: " + ", ".join(sorted(missing_types)))
    return config


def _recency_score(published_at: date | None, as_of: date, thresholds: dict) -> float:
    if published_at is None:
        return float(thresholds["missing_publication_date_score"])
    age_days = max(0, (as_of - published_at).days)
    fresh_within_days = int(thresholds["fresh_within_days"])
    stale_after_days = int(thresholds["stale_after_days"])
    if age_days <= fresh_within_days:
        return 100.0
    if age_days >= stale_after_days:
        return 0.0
    return 100.0 * (stale_after_days - age_days) / (stale_after_days - fresh_within_days)


def calculate_research_confidence(brief: StockResearchBrief, review: StockResearchReview) -> ResearchConfidenceComponents:
    """Score evidence coverage after the skeptical review, without model self-assessment."""

    config = load_research_confidence_config()
    quality = config["evidence_quality"]
    weights = config["weights"]
    thresholds = config["thresholds"]
    penalties = config["penalties"]

    evidence = brief.evidence
    evidence_quality = sum(float(quality[item.evidence_type.value]) for item in evidence) / len(evidence)
    evidence_breadth = min(1.0, len(evidence) / int(thresholds["target_evidence_count"])) * 100.0
    source_domains = {urlparse(str(item.url)).netloc.lower() for item in evidence}
    source_diversity = min(1.0, len(source_domains) / int(thresholds["target_source_domains"])) * 100.0
    evidence_recency = sum(_recency_score(item.published_at, brief.as_of, thresholds) for item in evidence) / len(evidence)

    base_score = (
        evidence_quality * float(weights["evidence_quality"])
        + evidence_breadth * float(weights["evidence_breadth"])
        + source_diversity * float(weights["source_diversity"])
        + evidence_recency * float(weights["evidence_recency"])
    )
    total_penalty = (
        len(review.unsupported_claim_ids) * int(penalties["unsupported_claim"])
        + len(review.missing_evidence) * int(penalties["missing_evidence"])
        + len(brief.unknowns) * int(penalties["unresolved_unknown"])
    )
    if review.verdict == "needs_more_evidence":
        total_penalty += int(penalties["needs_more_evidence_verdict"])
    elif review.verdict == "reject":
        total_penalty += int(penalties["reject_verdict"])
    total_penalty = min(total_penalty, int(penalties["maximum_total"]))

    return ResearchConfidenceComponents(
        evidence_quality=round(evidence_quality),
        evidence_breadth=round(evidence_breadth),
        source_diversity=round(source_diversity),
        evidence_recency=round(evidence_recency),
        base_score=round(base_score),
        total_penalty=total_penalty,
        score=round(max(0.0, min(100.0, base_score - total_penalty))),
    )
