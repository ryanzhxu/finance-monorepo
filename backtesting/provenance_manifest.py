from __future__ import annotations

import json
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


MANIFEST_SCHEMA_VERSION = "dataset_provenance_manifest_v1"
REPORT_SCHEMA_VERSION = "cache_only_coverage_report_v1"


class ProvenanceVerificationError(ValueError):
    """Raised when an immutable provenance artifact or cached file does not verify."""


class CertificationState(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    point_in_time_certified: bool = False
    universe_membership_point_in_time: bool = False
    historical_corporate_actions_complete: bool = False


class CacheFileRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: str
    relative_path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("symbol is required")
        return normalized


class DatasetProvenanceManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = MANIFEST_SCHEMA_VERSION
    dataset_id: str = Field(min_length=1)
    source: str = Field(min_length=1)
    retrieved_at: datetime
    adjustment_mode: str = Field(min_length=1)
    requested_symbols: tuple[str, ...]
    completed_symbols: tuple[str, ...]
    benchmark_symbols: tuple[str, ...]
    file_records: tuple[CacheFileRecord, ...] = ()
    certification: CertificationState
    limitations: tuple[str, ...] = ()
    manifest_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @field_validator("requested_symbols", "completed_symbols", "benchmark_symbols")
    @classmethod
    def normalize_symbols(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted({value.strip().upper() for value in values if value.strip()}))

    @model_validator(mode="after")
    def validate_coverage(self) -> DatasetProvenanceManifest:
        requested = set(self.requested_symbols)
        completed = set(self.completed_symbols)
        if not requested:
            raise ValueError("requested_symbols must not be empty")
        if not completed.issubset(requested):
            raise ValueError("completed_symbols must be a subset of requested_symbols")
        record_symbols = {record.symbol for record in self.file_records}
        if record_symbols != completed:
            raise ValueError("file_records must contain exactly the completed symbols")
        return self


class CacheOnlyCoverageReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = REPORT_SCHEMA_VERSION
    generated_at: datetime
    cache_only: bool = True
    redownload_performed: bool = False
    manifest: DatasetProvenanceManifest
    missing_symbols: tuple[str, ...]
    benchmark_coverage: dict[str, bool]
    report_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


def build_dataset_manifest(
    *,
    dataset_id: str,
    source: str,
    retrieved_at: datetime,
    adjustment_mode: str,
    requested_symbols: tuple[str, ...],
    completed_symbols: tuple[str, ...],
    benchmark_symbols: tuple[str, ...],
    file_records: tuple[CacheFileRecord, ...],
    certification: CertificationState,
    limitations: tuple[str, ...] = (),
) -> DatasetProvenanceManifest:
    manifest = DatasetProvenanceManifest(
        dataset_id=dataset_id,
        source=source,
        retrieved_at=retrieved_at,
        adjustment_mode=adjustment_mode,
        requested_symbols=requested_symbols,
        completed_symbols=completed_symbols,
        benchmark_symbols=benchmark_symbols,
        file_records=tuple(sorted(file_records, key=lambda record: record.symbol)),
        certification=certification,
        limitations=tuple(sorted(set(limitations))),
    )
    return manifest.model_copy(update={"manifest_sha256": _manifest_fingerprint(manifest)})


def build_cache_only_report(
    cache_dir: Path,
    *,
    dataset_id: str,
    source: str,
    adjustment_mode: str,
    requested_symbols: tuple[str, ...],
    benchmark_symbols: tuple[str, ...],
    certification: CertificationState,
    retrieved_at: datetime | None = None,
    file_names: Mapping[str, str] | None = None,
) -> CacheOnlyCoverageReport:
    generated_at = retrieved_at or datetime.now(timezone.utc)
    requested = tuple(sorted({symbol.strip().upper() for symbol in requested_symbols if symbol.strip()}))
    benchmarks = tuple(sorted({symbol.strip().upper() for symbol in benchmark_symbols if symbol.strip()}))
    records: list[CacheFileRecord] = []
    for symbol in requested:
        relative_path = (file_names or {}).get(symbol, f"{symbol}.csv")
        candidate = _cache_path(cache_dir, relative_path)
        if candidate.is_file():
            records.append(
                CacheFileRecord(
                    symbol=symbol,
                    relative_path=relative_path,
                    sha256=_sha256_file(candidate),
                    size_bytes=candidate.stat().st_size,
                )
            )
    completed = tuple(record.symbol for record in records)
    missing = tuple(sorted(set(requested) - set(completed)))
    benchmark_coverage = {
        symbol: _cache_path(cache_dir, (file_names or {}).get(symbol, f"{symbol}.csv")).is_file()
        for symbol in benchmarks
    }
    limitations = _limitations(certification, missing, benchmark_coverage)
    manifest = build_dataset_manifest(
        dataset_id=dataset_id,
        source=source,
        retrieved_at=generated_at,
        adjustment_mode=adjustment_mode,
        requested_symbols=requested,
        completed_symbols=completed,
        benchmark_symbols=benchmarks,
        file_records=tuple(records),
        certification=certification,
        limitations=limitations,
    )
    report = CacheOnlyCoverageReport(
        generated_at=generated_at,
        manifest=manifest,
        missing_symbols=missing,
        benchmark_coverage=benchmark_coverage,
    )
    return report.model_copy(update={"report_sha256": _report_fingerprint(report)})


def verify_manifest(manifest: DatasetProvenanceManifest) -> None:
    if manifest.manifest_sha256 != _manifest_fingerprint(manifest):
        raise ProvenanceVerificationError("dataset provenance manifest fingerprint does not match its contents")


def verify_cached_files(cache_dir: Path, manifest: DatasetProvenanceManifest) -> None:
    verify_manifest(manifest)
    for record in manifest.file_records:
        path = _cache_path(cache_dir, record.relative_path)
        if not path.is_file():
            raise ProvenanceVerificationError(f"cached file is missing: {record.relative_path}")
        if _sha256_file(path) != record.sha256 or path.stat().st_size != record.size_bytes:
            raise ProvenanceVerificationError(f"cached file changed: {record.relative_path}")


def verify_report(report: CacheOnlyCoverageReport) -> None:
    verify_manifest(report.manifest)
    if report.report_sha256 != _report_fingerprint(report):
        raise ProvenanceVerificationError("coverage report fingerprint does not match its contents")


def _manifest_fingerprint(manifest: DatasetProvenanceManifest) -> str:
    return _fingerprint(manifest.model_dump(mode="json", exclude={"manifest_sha256"}))


def _report_fingerprint(report: CacheOnlyCoverageReport) -> str:
    return _fingerprint(report.model_dump(mode="json", exclude={"report_sha256"}))


def _limitations(
    certification: CertificationState,
    missing: tuple[str, ...],
    benchmark_coverage: Mapping[str, bool],
) -> tuple[str, ...]:
    limitations: set[str] = set()
    if not certification.point_in_time_certified:
        limitations.add("Point-in-time certification is false; this artifact is experimental only.")
    if not certification.universe_membership_point_in_time:
        limitations.add("Universe membership is not point-in-time certified; survivorship bias remains possible.")
    if not certification.historical_corporate_actions_complete:
        limitations.add("Historical corporate-action completeness is not certified.")
    if missing:
        limitations.add(f"Missing requested symbols: {', '.join(missing)}.")
    missing_benchmarks = tuple(symbol for symbol, present in benchmark_coverage.items() if not present)
    if missing_benchmarks:
        limitations.add(f"Missing benchmark coverage: {', '.join(missing_benchmarks)}.")
    return tuple(sorted(limitations))


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _cache_path(cache_dir: Path, relative_path: str) -> Path:
    root = cache_dir.resolve()
    candidate = (root / relative_path).resolve()
    if candidate == root or root not in candidate.parents:
        raise ValueError("cache file path must remain inside cache_dir")
    return candidate


def _fingerprint(payload: Mapping[str, Any]) -> str:
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return sha256(serialized.encode("utf-8")).hexdigest()
