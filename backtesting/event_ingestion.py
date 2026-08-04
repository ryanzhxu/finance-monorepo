from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
from bisect import bisect_left, bisect_right
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from enum import StrEnum
from pathlib import Path
from typing import Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .event_library import EventEvidence, MarketImpact, MarketShockEvent, ProvenanceStatus


class IngestionStatus(StrEnum):
    COMPLETE = "complete"
    MISSING_EVIDENCE = "missing_evidence"
    SYSTEMIC_PROVIDER_FAILURE = "systemic_provider_failure"


class MissingEvidenceError(RuntimeError):
    """The source did not provide enough evidence to complete an event."""


class ProviderFailureError(RuntimeError):
    """The source failed systemically and should be retried later."""


@dataclass(frozen=True)
class EvidencePayload:
    evidence: EventEvidence
    raw_payload: bytes
    as_of: date | None = None
    revision: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.raw_payload, bytes):
            raise TypeError("raw_payload must be bytes")

    @property
    def content_sha256(self) -> str:
        return hashlib.sha256(self.raw_payload).hexdigest()


@dataclass(frozen=True)
class MarketPriceWindow:
    symbol: str
    prices: Mapping[date, float]
    benchmark: str
    benchmark_prices: Mapping[date, float]
    provenance: EvidencePayload | None = None


class ManifestSource(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence: EventEvidence
    role: Literal["event_evidence", "market_prices"]
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    raw_artifact: str
    as_of: date | None = None
    revision: str | None = None


class ProvenanceManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    manifest_version: int = Field(default=1, ge=1)
    event_id: str
    event_version: int = Field(ge=1)
    status: IngestionStatus
    created_at: datetime
    sources: tuple[ManifestSource, ...] = ()
    event_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    error: str | None = None
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_manifest(self) -> ProvenanceManifest:
        if self.status == IngestionStatus.COMPLETE:
            if not self.sources:
                raise ValueError("complete manifests require source evidence")
            if self.event_sha256 is None:
                raise ValueError("complete manifests require an event hash")
            if self.error is not None:
                raise ValueError("complete manifests cannot contain an error")
        elif self.event_sha256 is not None:
            raise ValueError("incomplete manifests cannot contain an event hash")
        elif self.error is None:
            raise ValueError("incomplete manifests require an error")

        expected = _sha256_json(self.model_dump(mode="json", exclude={"manifest_sha256"}))
        if self.manifest_sha256 != expected:
            raise ValueError("manifest hash does not match its immutable contents")
        return self


@dataclass(frozen=True)
class IngestedEvent:
    event: MarketShockEvent
    manifest: ProvenanceManifest


@dataclass(frozen=True)
class IngestionFailure:
    event_id: str
    status: IngestionStatus
    error: str
    manifest_sha256: str


@dataclass(frozen=True)
class IngestionBatchResult:
    records: tuple[IngestedEvent, ...]
    skipped_event_ids: tuple[str, ...]
    failures: tuple[IngestionFailure, ...]
    completed_event_ids: tuple[str, ...]


EvidenceLoader: TypeAlias = Callable[[MarketShockEvent], Sequence[EvidencePayload]]
PriceLoader: TypeAlias = Callable[[MarketShockEvent], MarketPriceWindow]


def default_event_artifact_root() -> Path:
    configured = os.getenv("BACKTESTING_EVENT_ARTIFACT_DIR")
    if configured:
        return Path(configured)
    return Path.home() / ".cache" / "finance-monorepo" / "event-ingestion"


class EventIngestionStore:
    """Private, append-only storage for raw evidence, manifests, events, and checkpoints."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def write_raw_artifact(self, payload: EvidencePayload) -> str:
        relative_path = Path("raw") / f"{payload.content_sha256}.bin"
        destination = self.root / relative_path
        if destination.exists():
            if destination.read_bytes() != payload.raw_payload:
                raise ValueError(f"raw artifact hash collision at {relative_path}")
            return relative_path.as_posix()
        _atomic_write(destination, payload.raw_payload)
        return relative_path.as_posix()

    def write_manifest(self, manifest: ProvenanceManifest) -> None:
        destination = (
            self.root
            / "manifests"
            / f"{manifest.event_id}-v{manifest.event_version}-{manifest.manifest_sha256}.json"
        )
        serialized = manifest.model_dump_json(indent=2).encode("utf-8")
        if destination.exists():
            existing = ProvenanceManifest.model_validate_json(destination.read_text(encoding="utf-8"))
            if existing != manifest:
                raise ValueError(f"immutable manifest collision at {destination}")
            return
        _atomic_write(destination, serialized)

    def write_event(self, event: MarketShockEvent) -> None:
        destination = self.root / "events" / f"{event.event_id}-v{event.version}.json"
        serialized = event.model_dump_json(indent=2).encode("utf-8")
        if destination.exists():
            existing = MarketShockEvent.model_validate_json(destination.read_text(encoding="utf-8"))
            if existing != event:
                raise ValueError(f"immutable event collision at {destination}")
            return
        _atomic_write(destination, serialized)

    def load_completed(self, batch_id: str) -> set[str]:
        checkpoint = self._checkpoint_path(batch_id)
        if not checkpoint.exists():
            return set()
        payload = json.loads(checkpoint.read_text(encoding="utf-8"))
        completed = payload.get("completed_event_ids")
        if payload.get("batch_id") != batch_id or not isinstance(completed, list) or not all(
            isinstance(event_id, str) for event_id in completed
        ):
            raise ValueError(f"invalid checkpoint for batch {batch_id}")
        return set(completed)

    def save_completed(self, batch_id: str, event_ids: Iterable[str]) -> None:
        payload = {
            "batch_id": batch_id,
            "completed_event_ids": sorted(set(event_ids)),
        }
        _atomic_write(
            self._checkpoint_path(batch_id),
            json.dumps(payload, sort_keys=True, indent=2).encode("utf-8"),
        )

    def _checkpoint_path(self, batch_id: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", batch_id):
            raise ValueError("batch_id may contain only letters, numbers, dot, underscore, and hyphen")
        return self.root / "checkpoints" / f"{batch_id}.json"


def ingest_events(
    events: Iterable[MarketShockEvent],
    *,
    batch_id: str,
    evidence_loader: EvidenceLoader,
    price_loader: PriceLoader,
    store: EventIngestionStore,
    attempted_at: datetime | None = None,
) -> IngestionBatchResult:
    event_list = tuple(events)
    event_ids = [event.event_id for event in event_list]
    if len(event_ids) != len(set(event_ids)):
        raise ValueError("event batch contains duplicate event IDs")

    attempt_time = attempted_at or datetime.now(timezone.utc)
    completed = store.load_completed(batch_id)
    skipped: list[str] = []
    records: list[IngestedEvent] = []
    failures: list[IngestionFailure] = []

    for event in event_list:
        if event.event_id in completed:
            skipped.append(event.event_id)
            continue

        sources: list[ManifestSource] = []
        try:
            payloads = tuple(evidence_loader(event))
            if not payloads:
                raise MissingEvidenceError("source returned no evidence")
            for payload in payloads:
                raw_artifact = store.write_raw_artifact(payload)
                sources.append(
                    ManifestSource(
                        evidence=payload.evidence,
                        role="event_evidence",
                        content_sha256=payload.content_sha256,
                        raw_artifact=raw_artifact,
                        as_of=payload.as_of,
                        revision=payload.revision,
                    )
                )

            price_window = price_loader(event)
            if price_window.provenance is None:
                raise MissingEvidenceError("price history provenance is missing")
            price_raw_artifact = store.write_raw_artifact(price_window.provenance)
            sources.append(
                ManifestSource(
                    evidence=price_window.provenance.evidence,
                    role="market_prices",
                    content_sha256=price_window.provenance.content_sha256,
                    raw_artifact=price_raw_artifact,
                    as_of=price_window.provenance.as_of,
                    revision=price_window.provenance.revision,
                )
            )
            impact = calculate_market_impact(event.impact, price_window)
            measured_event = event.model_copy(
                update={
                    "impact": impact,
                    "provenance_status": ProvenanceStatus.NEEDS_REVIEW,
                }
            )
            manifest = build_manifest(
                event=measured_event,
                status=IngestionStatus.COMPLETE,
                created_at=attempt_time,
                sources=sources,
            )
            store.write_event(measured_event)
            store.write_manifest(manifest)
            completed.add(event.event_id)
            records.append(IngestedEvent(event=measured_event, manifest=manifest))
        except MissingEvidenceError as exc:
            manifest = build_manifest(
                event=event,
                status=IngestionStatus.MISSING_EVIDENCE,
                created_at=attempt_time,
                sources=sources,
                error=str(exc),
            )
            store.write_manifest(manifest)
            failures.append(
                IngestionFailure(
                    event_id=event.event_id,
                    status=manifest.status,
                    error=str(exc),
                    manifest_sha256=manifest.manifest_sha256,
                )
            )
        except ProviderFailureError as exc:
            manifest = build_manifest(
                event=event,
                status=IngestionStatus.SYSTEMIC_PROVIDER_FAILURE,
                created_at=attempt_time,
                sources=sources,
                error=str(exc),
            )
            store.write_manifest(manifest)
            failures.append(
                IngestionFailure(
                    event_id=event.event_id,
                    status=manifest.status,
                    error=str(exc),
                    manifest_sha256=manifest.manifest_sha256,
                )
            )
        finally:
            store.save_completed(batch_id, completed)

    return IngestionBatchResult(
        records=tuple(records),
        skipped_event_ids=tuple(skipped),
        failures=tuple(failures),
        completed_event_ids=tuple(sorted(completed)),
    )


def build_manifest(
    *,
    event: MarketShockEvent,
    status: IngestionStatus,
    created_at: datetime,
    sources: Sequence[ManifestSource] = (),
    error: str | None = None,
) -> ProvenanceManifest:
    event_hash = _sha256_json(event.model_dump(mode="json")) if status == IngestionStatus.COMPLETE else None
    payload = {
        "manifest_version": 1,
        "event_id": event.event_id,
        "event_version": event.version,
        "status": status,
        "created_at": created_at,
        "sources": list(sources),
        "event_sha256": event_hash,
        "error": error,
    }
    payload["manifest_sha256"] = _sha256_json(payload)
    return ProvenanceManifest.model_validate(payload)


def calculate_market_impact(spec: MarketImpact, window: MarketPriceWindow) -> MarketImpact:
    if window.benchmark.strip().upper() != spec.benchmark:
        raise ValueError("price window benchmark does not match event benchmark")

    prices = _normalize_prices(window.prices, "subject")
    benchmark_prices = _normalize_prices(window.benchmark_prices, "benchmark")
    common_dates = sorted(set(prices) & set(benchmark_prices))
    start_position = bisect_left(common_dates, spec.window_start)
    end_position = bisect_right(common_dates, spec.window_end) - 1
    if start_position == 0:
        raise MissingEvidenceError("price history missing pre-event baseline")
    if end_position < start_position:
        raise MissingEvidenceError("price history missing the impact window")

    baseline_position = start_position - 1
    subject_path = [prices[day] for day in common_dates[baseline_position : end_position + 1]]
    benchmark_path = [benchmark_prices[day] for day in common_dates[baseline_position : end_position + 1]]
    subject_event = subject_path[1:]
    benchmark_event = benchmark_path[1:]
    subject_return = subject_event[-1] / subject_event[0] - 1
    benchmark_return = benchmark_event[-1] / benchmark_event[0] - 1
    relative_return_pct = round((subject_return - benchmark_return) * 100, 6)

    running_peak = subject_path[0]
    drawdowns: list[float] = []
    for value in subject_path:
        running_peak = max(running_peak, value)
        drawdowns.append(value / running_peak - 1)
    peak_drawdown_pct = round(min(drawdowns) * 100, 6)

    daily_returns = [current / previous - 1 for previous, current in zip(subject_path, subject_path[1:])]
    average_return = sum(daily_returns) / len(daily_returns) if daily_returns else 0.0
    volatility = math.sqrt(
        sum((value - average_return) ** 2 for value in daily_returns) / len(daily_returns)
    ) * math.sqrt(252) * 100 if daily_returns else None

    trough_position = min(range(len(subject_path)), key=subject_path.__getitem__)
    recovery_position = next(
        (
            position
            for position in range(trough_position + 1, len(subject_path))
            if subject_path[position] >= subject_path[0]
        ),
        None,
    )
    recovery_days = recovery_position - trough_position if recovery_position is not None else None

    return spec.model_copy(
        update={
            "measurement_status": "measured",
            "benchmark_relative_return_pct": relative_return_pct,
            "peak_drawdown_pct": peak_drawdown_pct,
            "volatility_peak": round(volatility, 6) if volatility is not None else None,
            "recovery_days": recovery_days,
        }
    )


def _normalize_prices(values: Mapping[date, float], label: str) -> dict[date, float]:
    normalized: dict[date, float] = {}
    for observed_on, raw_value in values.items():
        value = float(raw_value)
        if not math.isfinite(value) or value <= 0:
            raise MissingEvidenceError(f"{label} price history contains an invalid value")
        normalized[observed_on] = value
    if not normalized:
        raise MissingEvidenceError(f"{label} price history is empty")
    return normalized


def _sha256_json(payload: object) -> str:
    serialized = json.dumps(_json_ready(payload), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _json_ready(payload: object) -> object:
    if isinstance(payload, BaseModel):
        return payload.model_dump(mode="json")
    if isinstance(payload, Mapping):
        return {str(key): _json_ready(value) for key, value in payload.items()}
    if isinstance(payload, (list, tuple)):
        return [_json_ready(value) for value in payload]
    if isinstance(payload, datetime):
        value = payload.isoformat()
        return value.replace("+00:00", "Z") if payload.utcoffset() == timedelta(0) else value
    if isinstance(payload, date):
        return payload.isoformat()
    if isinstance(payload, StrEnum):
        return payload.value
    return payload


def _atomic_write(destination: Path, content: bytes) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=f".{destination.name}.", delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(content)
    try:
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
