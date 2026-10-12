from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from analyst_service.core.research_provider import ResearchCompletion, ResearchStage, StructuredResearchProvider
from analyst_service.core.research_confidence import calculate_research_confidence
from analyst_service.core.stock_research import (
    CandidateDiscoveryBrief,
    CandidateDiscoveryContext,
    CandidateHypothesis,
    StockResearchBrief,
    StockResearchContext,
    StockResearchReview,
    build_candidate_discovery_prompt,
    build_evidence_verification_prompt,
    build_skeptic_review_prompt,
    stock_research_brief_output_schema,
    validate_stock_research_review,
)
from shared.models import EntryBlock


class StockResearchOrchestrationError(RuntimeError):
    pass


@dataclass(frozen=True)
class CandidateResearchResult:
    candidate: CandidateHypothesis
    brief: StockResearchBrief
    review: StockResearchReview
    entry: EntryBlock | None


class StockResearchOrchestrator:
    def __init__(
        self,
        provider: StructuredResearchProvider,
        *,
        max_attempts: int = 2,
        max_provider_attempts: int = 6,
    ) -> None:
        self._provider = provider
        self._max_attempts = max_attempts
        self._max_provider_attempts = max_provider_attempts
        self._provider_completions: list[ResearchCompletion] = []

    @property
    def provider_completions(self) -> tuple[ResearchCompletion, ...]:
        return tuple(self._provider_completions)

    async def discover(self, context: CandidateDiscoveryContext) -> CandidateDiscoveryBrief:
        prompt = build_candidate_discovery_prompt(context)
        discovery, completion = await self._complete_json(
            prompt,
            CandidateDiscoveryBrief,
            require_web_search=True,
            stage="discovery",
        )
        self._validate_grounding(discovery, completion)
        return discovery

    async def verify(self, context: StockResearchContext) -> StockResearchBrief:
        brief, _ = await self._complete_json(
            build_evidence_verification_prompt(context),
            StockResearchBrief,
            require_web_search=False,
            response_schema=stock_research_brief_output_schema(),
            stage="verification",
        )
        return brief

    async def review(self, context: StockResearchContext, brief: StockResearchBrief) -> StockResearchReview:
        review, _ = await self._complete_json(
            build_skeptic_review_prompt(context, brief),
            StockResearchReview,
            require_web_search=False,
            stage="review",
        )
        return validate_stock_research_review(review, brief)

    async def research_candidate(
        self,
        candidate: CandidateHypothesis,
        discovery: CandidateDiscoveryBrief,
        structured_analysis: dict[str, Any],
        *,
        entry: EntryBlock | None = None,
        analogy: str | None = None,
    ) -> CandidateResearchResult:
        evidence = [evidence for evidence in discovery.evidence if evidence.id in candidate.evidence_ids]
        context = StockResearchContext(
            symbol=candidate.symbol,
            as_of=discovery.as_of,
            research_question=candidate.thesis,
            analogy=analogy,
            structured_analysis=structured_analysis,
            evidence=evidence,
        )
        brief = await self.verify(context)
        review = await self.review(context, brief)
        confidence = calculate_research_confidence(brief, review)
        brief = brief.model_copy(
            update={"confidence": confidence.score, "confidence_components": confidence.model_dump(mode="json")}
        )
        return CandidateResearchResult(candidate=candidate, brief=brief, review=review, entry=entry)

    async def _complete_json(
        self,
        prompt: str,
        model_type: type[CandidateDiscoveryBrief] | type[StockResearchBrief] | type[StockResearchReview],
        *,
        require_web_search: bool,
        stage: ResearchStage,
        response_schema: dict[str, Any] | None = None,
    ) -> tuple[CandidateDiscoveryBrief | StockResearchBrief | StockResearchReview, ResearchCompletion]:
        last_error: Exception | None = None
        for _ in range(self._max_attempts):
            if len(self._provider_completions) >= self._max_provider_attempts:
                raise StockResearchOrchestrationError(
                    "Research provider attempt budget exhausted; no additional provider call was made"
                ) from last_error
            completion = await self._provider.complete(
                prompt,
                response_schema or model_type.model_json_schema(),
                require_web_search=require_web_search,
                stage=stage,
            )
            self._provider_completions.append(completion)
            try:
                result = model_type.model_validate_json(completion.text)
                return result, completion
            except ValidationError as exc:
                last_error = exc
        raise StockResearchOrchestrationError("Research provider returned invalid contract output") from last_error

    @staticmethod
    def _validate_grounding(discovery: CandidateDiscoveryBrief, completion: ResearchCompletion) -> None:
        source_urls = {url.rstrip("/") for url in completion.source_urls}
        if not source_urls:
            raise StockResearchOrchestrationError("Candidate discovery returned no grounded source URLs")
        ungrounded = sorted(str(evidence.url).rstrip("/") for evidence in discovery.evidence if str(evidence.url).rstrip("/") not in source_urls)
        if ungrounded:
            raise StockResearchOrchestrationError(
                "Candidate discovery included evidence not returned by the research provider: " + ", ".join(ungrounded)
            )
