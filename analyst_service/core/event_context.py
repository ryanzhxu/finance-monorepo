from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Literal

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, field_validator

from backtesting.event_library import EventType, MarketShockEvent, ProvenanceStatus
from shared.enums import Freshness, MarketRegime


class ContextStatus(StrEnum):
    AVAILABLE = "available"
    UNKNOWN = "unknown"


class ContextObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: str
    as_of: date
    freshness: Freshness
    volatility_pct: float | None = Field(default=None, ge=0)
    drawdown_pct: float | None = None
    gap_pct: float | None = None
    volume_ratio: float | None = Field(default=None, ge=0)
    sector: str | None = None
    macro_regime: MarketRegime | None = None

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("symbol is required")
        return normalized

    @field_validator("sector")
    @classmethod
    def normalize_sector(cls, value: str | None) -> str | None:
        return value.strip().lower() if value and value.strip() else None


class ContextPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    volatility_risk_pct: float = Field(default=30.0, ge=0)
    drawdown_risk_pct: float = Field(default=-10.0)
    gap_risk_pct: float = Field(default=-5.0)
    volume_stress_ratio: float = Field(default=2.0, ge=0)
    stale_freshness: tuple[Freshness, ...] = (Freshness.STALE, Freshness.MISSING)


class ContextEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str
    title: str
    source_urls: tuple[AnyHttpUrl, ...]
    retrieved_at: tuple[datetime, ...]
    provenance_status: ProvenanceStatus


class EventContextResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: ContextStatus
    risk_flags: tuple[str, ...] = ()
    matched_event_ids: tuple[str, ...] = ()
    evidence: tuple[ContextEvidence, ...] = ()
    unknowns: tuple[str, ...] = ()
    features: dict[str, float | str | None] = {}


def evaluate_event_context(
    observation: ContextObservation,
    events: list[MarketShockEvent],
    *,
    policy: ContextPolicy | None = None,
) -> EventContextResult:
    """Return bounded event context without changing any analyst decision value."""

    thresholds = policy or ContextPolicy()
    risk_flags: set[str] = set()
    unknowns: set[str] = set()
    features: dict[str, float | str | None] = {
        "volatility_pct": observation.volatility_pct,
        "drawdown_pct": observation.drawdown_pct,
        "gap_pct": observation.gap_pct,
        "volume_ratio": observation.volume_ratio,
        "macro_regime": observation.macro_regime.value if observation.macro_regime else None,
    }

    if observation.freshness in thresholds.stale_freshness:
        risk_flags.add("stale_data")
        unknowns.add("observation_data_stale")

    if observation.volatility_pct is not None and observation.volatility_pct >= thresholds.volatility_risk_pct:
        risk_flags.add("liquidity_stress")
    if observation.drawdown_pct is not None and observation.drawdown_pct <= thresholds.drawdown_risk_pct:
        risk_flags.add("liquidity_stress")
    if observation.gap_pct is not None and observation.gap_pct <= thresholds.gap_risk_pct:
        risk_flags.add("gap_risk")
    if observation.volume_ratio is not None and observation.volume_ratio >= thresholds.volume_stress_ratio:
        risk_flags.add("liquidity_stress")

    if observation.freshness in thresholds.stale_freshness:
        return _result(risk_flags, (), (), unknowns, features)

    eligible_events = [event for event in events if _eligible_event(event, observation)]
    if not eligible_events:
        unknowns.add("no_verified_event_match")
        return _result(risk_flags, (), (), unknowns, features)

    for event in eligible_events:
        if event.event_type in {EventType.LIQUIDITY_CREDIT_STRESS, EventType.SOVEREIGN_BANKING_CRISIS}:
            risk_flags.add("liquidity_stress")
        if event.event_type == EventType.REGULATORY_TRADE:
            risk_flags.add("export_controls_risk")
        if observation.sector and observation.sector in {sector.lower() for sector in event.affected_sectors}:
            risk_flags.add("sector_exposure")
        if observation.macro_regime == MarketRegime.RISK_OFF and event.event_type in {
            EventType.MONETARY_INFLATION,
            EventType.LIQUIDITY_CREDIT_STRESS,
            EventType.SOVEREIGN_BANKING_CRISIS,
        }:
            risk_flags.add("macro_event_window")

    evidence = tuple(_evidence_for(event) for event in eligible_events)
    return _result(
        risk_flags,
        tuple(event.event_id for event in eligible_events),
        evidence,
        unknowns,
        features,
    )


def _eligible_event(event: MarketShockEvent, observation: ContextObservation) -> bool:
    if event.provenance_status != ProvenanceStatus.VERIFIED:
        return False
    if event.start_date > observation.as_of:
        return False
    if event.end_date and observation.as_of > event.end_date:
        return False
    return all(evidence.retrieved_at.date() <= observation.as_of for evidence in event.evidence)


def _evidence_for(event: MarketShockEvent) -> ContextEvidence:
    return ContextEvidence(
        event_id=event.event_id,
        title=event.title,
        source_urls=tuple(evidence.source_url for evidence in event.evidence),
        retrieved_at=tuple(evidence.retrieved_at for evidence in event.evidence),
        provenance_status=event.provenance_status,
    )


def _result(
    risk_flags: set[str],
    matched_event_ids: tuple[str, ...],
    evidence: tuple[ContextEvidence, ...],
    unknowns: set[str],
    features: dict[str, float | str | None],
) -> EventContextResult:
    return EventContextResult(
        status=ContextStatus.AVAILABLE if matched_event_ids else ContextStatus.UNKNOWN,
        risk_flags=tuple(sorted(risk_flags)),
        matched_event_ids=matched_event_ids,
        evidence=evidence,
        unknowns=tuple(sorted(unknowns)),
        features=features,
    )
