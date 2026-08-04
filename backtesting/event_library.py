from __future__ import annotations

import json
from datetime import date, datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, field_validator, model_validator


class EventType(StrEnum):
    LIQUIDITY_CREDIT_STRESS = "liquidity_credit_stress"
    SOVEREIGN_BANKING_CRISIS = "sovereign_banking_crisis"
    PANDEMIC_PUBLIC_HEALTH = "pandemic_public_health"
    WAR_GEOPOLITICAL = "war_geopolitical"
    ENERGY_COMMODITY = "energy_commodity"
    REGULATORY_TRADE = "regulatory_trade"
    CYBER_INFRASTRUCTURE = "cyber_infrastructure"
    ISSUER_ACCOUNTING = "issuer_accounting"
    MONETARY_INFLATION = "monetary_inflation"


class ProvenanceStatus(StrEnum):
    FIXTURE = "fixture"
    VERIFIED = "verified"
    NEEDS_REVIEW = "needs_review"


class MarketImpact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    measurement_status: Literal["unmeasured", "measured"] = "unmeasured"
    window_start: date
    window_end: date
    benchmark: str = "SPY"
    peak_drawdown_pct: float | None = None
    volatility_peak: float | None = None
    recovery_days: int | None = Field(default=None, ge=0)
    recovery_definition: str = "Return to the pre-event closing level."

    @field_validator("benchmark")
    @classmethod
    def normalize_benchmark(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("benchmark is required")
        return normalized

    @model_validator(mode="after")
    def validate_window(self) -> MarketImpact:
        if self.window_end < self.window_start:
            raise ValueError("impact window_end must not precede window_start")
        if self.measurement_status == "unmeasured" and any(
            value is not None for value in (self.peak_drawdown_pct, self.volatility_peak, self.recovery_days)
        ):
            raise ValueError("unmeasured impact cannot contain measured metrics")
        return self


class EventEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_url: AnyHttpUrl
    publisher: str
    source_type: Literal["regulator", "government", "issuer", "academic", "exchange"]
    published_on: date | None = None
    retrieved_at: datetime
    note: str | None = None

    @field_validator("publisher")
    @classmethod
    def validate_publisher(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("publisher is required")
        return normalized


class MarketShockEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)+$")
    version: int = Field(ge=1)
    event_type: EventType
    title: str
    start_date: date
    end_date: date | None = None
    geography: list[str] = Field(min_length=1)
    affected_sectors: list[str] = Field(min_length=1)
    trigger_description: str
    policy_response: str | None = None
    transmission_channels: list[str] = Field(min_length=1)
    known_confounders: list[str] = Field(default_factory=list)
    impact: MarketImpact
    evidence: list[EventEvidence] = Field(min_length=1)
    provenance_status: ProvenanceStatus

    @field_validator("title", "trigger_description")
    @classmethod
    def validate_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("text field is required")
        return normalized

    @model_validator(mode="after")
    def validate_dates_and_provenance(self) -> MarketShockEvent:
        if self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date must not precede start_date")
        if self.provenance_status == ProvenanceStatus.VERIFIED and any(
            evidence.source_type not in {"regulator", "government", "issuer", "academic", "exchange"}
            for evidence in self.evidence
        ):
            raise ValueError("verified events require an allowed primary-source type")
        return self


FIXTURE_PATH = Path(__file__).resolve().parent / "events" / "fixtures.json"


def load_event_fixtures(path: Path = FIXTURE_PATH) -> list[MarketShockEvent]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("event fixture file must contain a JSON list")
    events = [MarketShockEvent.model_validate(item) for item in payload]
    event_ids = [event.event_id for event in events]
    if len(event_ids) != len(set(event_ids)):
        raise ValueError("event fixture IDs must be unique")
    return events
