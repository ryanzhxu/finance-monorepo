from __future__ import annotations

import json
import os
from datetime import date, datetime, timezone
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable, Mapping
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


HOLDOUT_REGISTRY_SCHEMA = "holdout_consumption_registry_v1"
SEC_BATCH_SCHEMA = "sec_batch_manifest_v1"
LEGACY_HOLDOUT_START = date(2023, 1, 1)
LEGACY_HOLDOUT_END = date(2024, 12, 31)
LEGACY_LABEL_VERSION = "next_open_low_v2"


class HoldoutConsumptionError(ValueError):
    """Raised when a final holdout evaluation is not permitted."""


class HoldoutConsumptionKey(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    model_version: str = Field(min_length=1)
    label_version: str = Field(min_length=1)
    feature_schema_version: str = Field(min_length=1)
    dataset_provenance_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    selection_artifact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    evaluation_config_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    holdout_start: date
    holdout_end: date

    @model_validator(mode="after")
    def validate_window(self) -> HoldoutConsumptionKey:
        if self.holdout_end < self.holdout_start:
            raise ValueError("holdout_end must not precede holdout_start")
        return self

    @property
    def value(self) -> str:
        return _fingerprint(self.model_dump(mode="json"))

    @property
    def slot(self) -> str:
        return _fingerprint(
            {
                "label_version": self.label_version,
                "holdout_start": self.holdout_start.isoformat(),
                "holdout_end": self.holdout_end.isoformat(),
            }
        )


class HoldoutRecordStatus(StrEnum):
    RESERVED = "reserved"
    CONSUMED = "consumed"


class SecFailureClass(StrEnum):
    MISSING_OR_UNMAPPED = "missing_or_unmapped"
    TRANSPORT = "transport"
    AUTH = "auth"
    RATE_LIMIT = "rate_limit"
    UNKNOWN_SYSTEMIC = "unknown_systemic"


class SecSymbolStatus(StrEnum):
    COMPLETED = "completed"
    MISSING_OR_UNMAPPED = "missing_or_unmapped"
    SYSTEMIC_FAILURE = "systemic_failure"


class SecFetchResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    cik: str = Field(pattern=r"^\d{10}$")
    cache_file: str = Field(min_length=1)
    observation_count: int = Field(ge=0)


class SecSymbolResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: str = Field(min_length=1)
    status: SecSymbolStatus
    cik: str | None = Field(default=None, pattern=r"^\d{10}$")
    failure_class: SecFailureClass | None = None
    detail: str | None = None
    cache_file: str | None = None
    observation_count: int | None = Field(default=None, ge=0)
    recorded_at: datetime

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("symbol is required")
        return normalized

    @model_validator(mode="after")
    def validate_status_fields(self) -> SecSymbolResult:
        if self.status == SecSymbolStatus.COMPLETED and self.failure_class is not None:
            raise ValueError("completed SEC results cannot contain a failure class")
        if (
            self.status == SecSymbolStatus.MISSING_OR_UNMAPPED
            and self.failure_class != SecFailureClass.MISSING_OR_UNMAPPED
        ):
            raise ValueError("missing SEC results require the missing_or_unmapped failure class")
        if self.status == SecSymbolStatus.SYSTEMIC_FAILURE and self.failure_class in {
            None,
            SecFailureClass.MISSING_OR_UNMAPPED,
        }:
            raise ValueError("systemic SEC results require a systemic failure class")
        return self


class SecBatchStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    SYSTEMIC_FAILURE = "systemic_failure"


class SecBatchManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = SEC_BATCH_SCHEMA
    run_id: str = Field(min_length=1)
    requested_symbols: tuple[str, ...]
    results: dict[str, SecSymbolResult] = {}
    status: SecBatchStatus = SecBatchStatus.RUNNING
    generated_at: datetime
    updated_at: datetime
    next_action: str

    @field_validator("requested_symbols")
    @classmethod
    def normalize_symbols(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        symbols = {value.strip().upper() for value in values if value.strip()}
        if not symbols:
            raise ValueError("at least one SEC symbol is required")
        return tuple(sorted(symbols))


class HoldoutConsumptionRegistry:
    """Private local ledger that reserves a holdout before labels are loaded."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def reserve_before_load(self, key: HoldoutConsumptionKey) -> None:
        registry = self._read()
        if key.value in registry["records"]:
            raise HoldoutConsumptionError(
                "identical final-holdout consumption key already exists; explicit approval is required before retrying"
            )
        if _legacy_holdout_matches(key):
            raise HoldoutConsumptionError(
                "the 2023-2024 final holdout is already consumed; explicit approval is required before reuse"
            )
        for record in registry["records"].values():
            if record["slot"] == key.slot:
                raise HoldoutConsumptionError(
                    "final-holdout window is already reserved or consumed by another evaluation configuration"
                )
        now = _now()
        registry["records"][key.value] = {
            "status": HoldoutRecordStatus.RESERVED.value,
            "slot": key.slot,
            "key": key.model_dump(mode="json"),
            "reserved_at": now,
        }
        self._write(registry)

    def finalize(
        self,
        key: HoldoutConsumptionKey,
        *,
        report: Mapping[str, Any],
        report_path: Path,
    ) -> None:
        registry = self._read()
        record = registry["records"].get(key.value)
        if record is None or record["status"] != HoldoutRecordStatus.RESERVED.value:
            raise HoldoutConsumptionError("final holdout must be reserved before it can be finalized")
        report_hash = _fingerprint(report)
        record.update(
            {
                "status": HoldoutRecordStatus.CONSUMED.value,
                "consumed_at": _now(),
                "report_sha256": report_hash,
                "report_path": str(report_path),
            }
        )
        self._write(registry)

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"schema_version": HOLDOUT_REGISTRY_SCHEMA, "records": {}}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise HoldoutConsumptionError("invalid holdout consumption registry") from exc
        if payload.get("schema_version") != HOLDOUT_REGISTRY_SCHEMA or not isinstance(payload.get("records"), dict):
            raise HoldoutConsumptionError("unsupported holdout consumption registry")
        return payload

    def _write(self, payload: Mapping[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{uuid4().hex}.tmp")
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, self.path)


class SecBatchLedger:
    """Checkpointed, adapter-driven SEC batch state; it never performs network I/O."""

    def __init__(self, path: Path, *, run_id: str, requested_symbols: tuple[str, ...], resume: bool = False) -> None:
        self.path = path
        normalized = tuple(sorted({symbol.strip().upper() for symbol in requested_symbols if symbol.strip()}))
        if not normalized:
            raise ValueError("at least one SEC symbol is required")
        if path.exists():
            if not resume:
                raise ValueError("existing SEC manifest requires explicit resume=True")
            self._manifest = SecBatchManifest.model_validate(json.loads(path.read_text(encoding="utf-8")))
            if self._manifest.run_id != run_id or self._manifest.requested_symbols != normalized:
                raise ValueError("resume run_id and requested symbols must match the checkpoint")
        else:
            now = datetime.now(timezone.utc)
            self._manifest = SecBatchManifest(
                run_id=run_id,
                requested_symbols=normalized,
                generated_at=now,
                updated_at=now,
                next_action="Process the unresolved symbols through an approved SEC adapter.",
            )
            self._checkpoint()

    @property
    def manifest(self) -> SecBatchManifest:
        return self._manifest

    def resume_symbols(self) -> tuple[str, ...]:
        return tuple(
            symbol
            for symbol in self._manifest.requested_symbols
            if symbol not in self._manifest.results
            or self._manifest.results[symbol].status == SecSymbolStatus.SYSTEMIC_FAILURE
        )

    def record_completed(self, symbol: str, result: SecFetchResult) -> None:
        self._record(
            SecSymbolResult(
                symbol=symbol,
                status=SecSymbolStatus.COMPLETED,
                cik=result.cik,
                cache_file=result.cache_file,
                observation_count=result.observation_count,
                recorded_at=datetime.now(timezone.utc),
            )
        )

    def record_missing(self, symbol: str, *, detail: str, cik: str | None = None) -> None:
        self._record(
            SecSymbolResult(
                symbol=symbol,
                status=SecSymbolStatus.MISSING_OR_UNMAPPED,
                cik=cik,
                failure_class=SecFailureClass.MISSING_OR_UNMAPPED,
                detail=detail[:300],
                recorded_at=datetime.now(timezone.utc),
            )
        )

    def record_systemic_failure(
        self,
        symbol: str,
        *,
        failure_class: SecFailureClass,
        detail: str,
        cik: str | None = None,
    ) -> None:
        if failure_class == SecFailureClass.MISSING_OR_UNMAPPED:
            raise ValueError("missing data must use record_missing")
        self._record(
            SecSymbolResult(
                symbol=symbol,
                status=SecSymbolStatus.SYSTEMIC_FAILURE,
                cik=cik,
                failure_class=failure_class,
                detail=detail[:300],
                recorded_at=datetime.now(timezone.utc),
            )
        )

    def finish(self) -> SecBatchManifest:
        unresolved = self.resume_symbols()
        systemic = any(result.status == SecSymbolStatus.SYSTEMIC_FAILURE for result in self._manifest.results.values())
        status = (
            SecBatchStatus.SYSTEMIC_FAILURE
            if systemic
            else SecBatchStatus.COMPLETED
            if not unresolved
            else SecBatchStatus.RUNNING
        )
        next_action = (
            f"Resume run {self._manifest.run_id}; do not request completed or missing symbols."
            if systemic
            else "No unresolved SEC symbols remain."
            if not unresolved
            else "Process the unresolved symbols through an approved SEC adapter."
        )
        self._manifest = self._manifest.model_copy(
            update={"status": status, "next_action": next_action, "updated_at": datetime.now(timezone.utc)}
        )
        self._checkpoint()
        return self._manifest

    def _record(self, result: SecSymbolResult) -> None:
        results = dict(self._manifest.results)
        results[result.symbol] = result
        self._manifest = self._manifest.model_copy(
            update={"results": results, "updated_at": datetime.now(timezone.utc)}
        )
        self._checkpoint()

    def _checkpoint(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{uuid4().hex}.tmp")
        temporary.write_text(self._manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, self.path)


def execute_sec_batch(
    ledger: SecBatchLedger,
    fetcher: Callable[[str], SecFetchResult | None],
) -> SecBatchManifest:
    """Run only the unresolved symbols through a caller-supplied, testable adapter."""

    for symbol in ledger.resume_symbols():
        try:
            result = fetcher(symbol)
        except Exception as exc:
            failure_class = classify_sec_failure(exc)
            if failure_class == SecFailureClass.MISSING_OR_UNMAPPED:
                ledger.record_missing(symbol, detail=f"{type(exc).__name__}: {exc}")
            else:
                ledger.record_systemic_failure(
                    symbol,
                    failure_class=failure_class,
                    detail=f"{type(exc).__name__}: {exc}",
                )
                break
        else:
            if result is None:
                ledger.record_missing(symbol, detail="SEC companyfacts payload is unavailable for this symbol")
            else:
                ledger.record_completed(symbol, result)
    return ledger.finish()


def classify_sec_failure(error: BaseException) -> SecFailureClass:
    response = getattr(error, "response", None)
    status_code = getattr(response, "status_code", None)
    if status_code == 404:
        return SecFailureClass.MISSING_OR_UNMAPPED
    if status_code in {401, 403}:
        return SecFailureClass.AUTH
    if status_code == 429:
        return SecFailureClass.RATE_LIMIT
    error_name = type(error).__name__.lower()
    if isinstance(error, (TimeoutError, ConnectionError)) or any(
        token in error_name for token in ("timeout", "connect", "dns", "transport")
    ):
        return SecFailureClass.TRANSPORT
    return SecFailureClass.UNKNOWN_SYSTEMIC


def _legacy_holdout_matches(key: HoldoutConsumptionKey) -> bool:
    return (
        key.label_version == LEGACY_LABEL_VERSION
        and key.holdout_start <= LEGACY_HOLDOUT_END
        and key.holdout_end >= LEGACY_HOLDOUT_START
    )


def _fingerprint(payload: Mapping[str, Any]) -> str:
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return sha256(serialized.encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
