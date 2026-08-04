from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from enum import StrEnum

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, field_validator

from shared.enums import Freshness


class AlertTrigger(StrEnum):
    ENTRY_ASSESSMENT_CHANGED = "entry_assessment_changed"
    IDEAL_BUY_ZONE_CHANGED = "ideal_buy_zone_changed"
    RISK_FLAG_CHANGED = "risk_flag_changed"
    DATA_QUALITY_BELOW_THRESHOLD = "data_quality_below_threshold"
    VERIFIED_EVENT_CONTEXT_ADDED = "verified_event_context_added"
    REGIME_CHANGED = "regime_changed"
    STALE_ANALYSIS = "stale_analysis"


class AlertLifecycle(StrEnum):
    NEW = "new"
    ACKNOWLEDGED = "acknowledged"
    DISMISSED = "dismissed"


class AlertEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    field: str
    value: str
    freshness: Freshness
    source: str


class WatchlistState(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: str
    observed_at: datetime
    entry_assessment: str | None = None
    in_ideal_buy_zone: bool | None = None
    risk_flags: tuple[str, ...] = ()
    data_quality_score: int = Field(ge=0, le=100)
    data_freshness: dict[str, Freshness] = {}
    verified_event_ids: tuple[str, ...] = ()
    regime: str | None = None
    analysis_url: AnyHttpUrl | None = None
    evidence: tuple[AlertEvidence, ...] = ()

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("symbol is required")
        return normalized


class AlertPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    data_quality_threshold: int = Field(default=70, ge=0, le=100)
    suppression_minutes: int = Field(default=60, ge=0)
    stale_freshness: tuple[Freshness, ...] = (Freshness.STALE, Freshness.MISSING)


class AlertStateSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    entry_assessment: str | None = None
    in_ideal_buy_zone: bool | None = None
    risk_flags: tuple[str, ...] = ()
    data_quality_score: int
    data_freshness: dict[str, Freshness] = {}
    verified_event_ids: tuple[str, ...] = ()
    regime: str | None = None


class WatchlistAlert(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    alert_id: str
    deduplication_key: str
    symbol: str
    trigger: AlertTrigger
    generated_at: datetime
    prior_state: AlertStateSummary
    current_state: AlertStateSummary
    evidence: tuple[AlertEvidence, ...] = ()
    reason: str
    uncertainty: tuple[str, ...] = ()
    suppression_until: datetime


def evaluate_watchlist_change(
    previous: WatchlistState,
    current: WatchlistState,
    *,
    policy: AlertPolicy | None = None,
) -> tuple[WatchlistAlert, ...]:
    if previous.symbol != current.symbol:
        raise ValueError("watchlist state symbols must match")
    thresholds = policy or AlertPolicy()
    prior_state = _state_summary(previous)
    current_state = _state_summary(current)
    alerts: list[WatchlistAlert] = []

    def add(trigger: AlertTrigger, reason: str, uncertainty: tuple[str, ...] = ()) -> None:
        deduplication_key = _deduplication_key(current.symbol, trigger, current_state)
        alerts.append(
            WatchlistAlert(
                alert_id=hashlib.sha256(
                    f"{deduplication_key}:{current.observed_at.isoformat()}".encode("utf-8")
                ).hexdigest()[:16],
                deduplication_key=deduplication_key,
                symbol=current.symbol,
                trigger=trigger,
                generated_at=current.observed_at,
                prior_state=prior_state,
                current_state=current_state,
                evidence=current.evidence,
                reason=reason,
                uncertainty=uncertainty,
                suppression_until=current.observed_at + timedelta(minutes=thresholds.suppression_minutes),
            )
        )

    if previous.entry_assessment != current.entry_assessment:
        add(AlertTrigger.ENTRY_ASSESSMENT_CHANGED, "Entry assessment changed.")
    if previous.in_ideal_buy_zone != current.in_ideal_buy_zone:
        add(AlertTrigger.IDEAL_BUY_ZONE_CHANGED, "Ideal buy-zone membership changed.")
    added_risk_flags = sorted(set(current.risk_flags) - set(previous.risk_flags))
    removed_risk_flags = sorted(set(previous.risk_flags) - set(current.risk_flags))
    if added_risk_flags or removed_risk_flags:
        changes = []
        if added_risk_flags:
            changes.append(f"added: {', '.join(added_risk_flags)}")
        if removed_risk_flags:
            changes.append(f"removed: {', '.join(removed_risk_flags)}")
        add(AlertTrigger.RISK_FLAG_CHANGED, f"Risk flags changed ({'; '.join(changes)}).")
    if current.data_quality_score < thresholds.data_quality_threshold and previous.data_quality_score >= thresholds.data_quality_threshold:
        add(AlertTrigger.DATA_QUALITY_BELOW_THRESHOLD, "Data quality fell below the configured threshold.")
    new_events = sorted(set(current.verified_event_ids) - set(previous.verified_event_ids))
    if new_events:
        add(AlertTrigger.VERIFIED_EVENT_CONTEXT_ADDED, f"Verified event context added: {', '.join(new_events)}.")
    if previous.regime != current.regime and current.regime is not None:
        add(AlertTrigger.REGIME_CHANGED, "Market regime context changed.")
    became_stale = any(value in thresholds.stale_freshness for value in current.data_freshness.values()) and not any(
        value in thresholds.stale_freshness for value in previous.data_freshness.values()
    )
    if became_stale:
        add(
            AlertTrigger.STALE_ANALYSIS,
            "Analysis freshness crossed into a stale or missing state.",
            ("Refresh before relying on this context.",),
        )

    return tuple(alerts)


class AlertLedger:
    """In-memory dry-run ledger; persistence and delivery remain separate adapters."""

    def __init__(self) -> None:
        self._last_emitted: dict[str, datetime] = {}
        self._muted_symbols: set[str] = set()
        self._lifecycle: dict[str, AlertLifecycle] = {}

    def emit(self, alerts: tuple[WatchlistAlert, ...]) -> tuple[WatchlistAlert, ...]:
        emitted: list[WatchlistAlert] = []
        for alert in alerts:
            if alert.symbol in self._muted_symbols:
                continue
            previous = self._last_emitted.get(alert.deduplication_key)
            suppression_duration = alert.suppression_until - alert.generated_at
            if previous is not None and alert.generated_at < previous + suppression_duration:
                continue
            self._last_emitted[alert.deduplication_key] = alert.generated_at
            self._lifecycle[alert.alert_id] = AlertLifecycle.NEW
            emitted.append(alert)
        return tuple(emitted)

    def mute(self, symbol: str) -> None:
        self._muted_symbols.add(symbol.strip().upper())

    def unmute(self, symbol: str) -> None:
        self._muted_symbols.discard(symbol.strip().upper())

    def acknowledge(self, alert_id: str) -> None:
        self._set_lifecycle(alert_id, AlertLifecycle.ACKNOWLEDGED)

    def dismiss(self, alert_id: str) -> None:
        self._set_lifecycle(alert_id, AlertLifecycle.DISMISSED)

    def lifecycle(self, alert_id: str) -> AlertLifecycle:
        return self._lifecycle[alert_id]

    def _set_lifecycle(self, alert_id: str, lifecycle: AlertLifecycle) -> None:
        if alert_id not in self._lifecycle:
            raise KeyError(f"unknown alert {alert_id}")
        self._lifecycle[alert_id] = lifecycle


def _deduplication_key(symbol: str, trigger: AlertTrigger, state: AlertStateSummary) -> str:
    serialized = json.dumps(state.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]
    return f"{symbol}:{trigger.value}:{digest}"


def _state_summary(state: WatchlistState) -> AlertStateSummary:
    return AlertStateSummary(
        entry_assessment=state.entry_assessment,
        in_ideal_buy_zone=state.in_ideal_buy_zone,
        risk_flags=state.risk_flags,
        data_quality_score=state.data_quality_score,
        data_freshness=state.data_freshness,
        verified_event_ids=state.verified_event_ids,
        regime=state.regime,
    )
