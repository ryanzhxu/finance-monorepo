from __future__ import annotations

import hashlib
import mimetypes
import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


DEFAULT_R2_BUCKET = "finance-research-data"


class R2ObjectClient(Protocol):
    def put_object(self, **kwargs: object) -> object: ...

    def head_object(self, **kwargs: object) -> dict[str, object]: ...

    def get_object(self, **kwargs: object) -> dict[str, object]: ...

    def list_objects_v2(self, **kwargs: object) -> dict[str, object]: ...


@dataclass(frozen=True)
class R2StorageSettings:
    account_id: str
    access_key_id: str
    secret_access_key: str
    bucket: str = DEFAULT_R2_BUCKET

    @classmethod
    def from_environment(cls, environment: Mapping[str, str] | None = None) -> R2StorageSettings:
        environment = os.environ if environment is None else environment
        values = {name: environment.get(name, "").strip() for name in ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY")}
        missing = [name for name, value in values.items() if not value]
        if missing:
            raise ValueError(f"missing R2 settings: {', '.join(missing)}")
        return cls(
            account_id=values["R2_ACCOUNT_ID"],
            access_key_id=values["R2_ACCESS_KEY_ID"],
            secret_access_key=values["R2_SECRET_ACCESS_KEY"],
            bucket=DEFAULT_R2_BUCKET,
        )

    @property
    def endpoint_url(self) -> str:
        return f"https://{self.account_id}.r2.cloudflarestorage.com"


@dataclass(frozen=True)
class R2Upload:
    source: Path
    key: str
    size_bytes: int
    sha256: str
    content_type: str


def build_upload_plan(source: Path, key_prefix: str) -> list[R2Upload]:
    if source.is_symlink():
        raise ValueError(f"refusing to upload symlink: {source}")
    source = source.resolve()
    if not source.exists():
        raise ValueError(f"upload source does not exist: {source}")
    prefix = _normalize_prefix(key_prefix)
    files = [source] if source.is_file() else sorted(path for path in source.rglob("*") if path.is_file())
    uploads = []
    for path in files:
        if path.is_symlink():
            raise ValueError(f"refusing to upload symlink: {path}")
        relative_path = path.name if source.is_file() else path.relative_to(source).as_posix()
        uploads.append(
            R2Upload(
                source=path,
                key=f"{prefix}/{relative_path}",
                size_bytes=path.stat().st_size,
                sha256=_sha256_file(path),
                content_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream",
            )
        )
    return uploads


def build_upload_plan_for_files(files: Iterable[tuple[Path, str]]) -> list[R2Upload]:
    uploads = []
    for source, key in files:
        if source.is_symlink() or not source.is_file():
            raise ValueError(f"upload source must be a regular file: {source}")
        normalized_key = _normalize_prefix(key)
        uploads.append(
            R2Upload(
                source=source,
                key=normalized_key,
                size_bytes=source.stat().st_size,
                sha256=_sha256_file(source),
                content_type=mimetypes.guess_type(source.name)[0] or "application/octet-stream",
            )
        )
    return uploads


def create_r2_client(settings: R2StorageSettings) -> R2ObjectClient:
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        endpoint_url=settings.endpoint_url,
        region_name="auto",
        aws_access_key_id=settings.access_key_id,
        aws_secret_access_key=settings.secret_access_key,
        # A checkpoint must fail and resume later rather than leave a run blocked forever.
        config=Config(connect_timeout=10, read_timeout=60, retries={"max_attempts": 3, "mode": "standard"}),
    )


def upload_plan(client: R2ObjectClient, bucket: str, uploads: Iterable[R2Upload]) -> list[dict[str, object]]:
    uploaded = []
    for upload in uploads:
        with upload.source.open("rb") as body:
            client.put_object(
                Bucket=bucket,
                Key=upload.key,
                Body=body,
                ContentType=upload.content_type,
                Metadata={"sha256": upload.sha256},
            )
        uploaded.append({"key": upload.key, "size_bytes": upload.size_bytes, "sha256": upload.sha256})
    return uploaded


def bucket_usage_bytes(client: R2ObjectClient, bucket: str) -> int:
    total = 0
    continuation_token: str | None = None
    while True:
        request: dict[str, object] = {"Bucket": bucket}
        if continuation_token is not None:
            request["ContinuationToken"] = continuation_token
        page = client.list_objects_v2(**request)
        total += sum(int(item.get("Size", 0)) for item in page.get("Contents", []) if isinstance(item, dict))
        if not page.get("IsTruncated"):
            return total
        continuation_token = page.get("NextContinuationToken") if isinstance(page.get("NextContinuationToken"), str) else None
        if continuation_token is None:
            raise ValueError("truncated R2 object listing did not return a continuation token")


def upload_verified_plan(
    client: R2ObjectClient,
    bucket: str,
    uploads: Iterable[R2Upload],
    *,
    storage_limit_bytes: int,
) -> list[dict[str, object]]:
    uploads = list(uploads)
    missing_or_changed = [upload for upload in uploads if not _matches_remote_object(client, bucket, upload)]
    projected_usage = bucket_usage_bytes(client, bucket) + sum(upload.size_bytes for upload in missing_or_changed)
    if projected_usage > storage_limit_bytes:
        raise ValueError(f"R2 storage guard: projected usage {projected_usage} exceeds limit {storage_limit_bytes}")
    uploaded = upload_plan(client, bucket, missing_or_changed)
    for upload in uploads:
        if not _matches_remote_object(client, bucket, upload):
            raise ValueError(f"R2 checksum verification failed for {upload.key}")
    return uploaded


def download_verified_plan(
    client: R2ObjectClient,
    bucket: str,
    uploads: Iterable[R2Upload],
    *,
    destination_dir: Path,
) -> list[dict[str, object]]:
    if destination_dir.exists() and not destination_dir.is_dir():
        raise ValueError(f"download destination must be a directory: {destination_dir}")
    destination_dir.mkdir(parents=True, exist_ok=True)

    downloaded = []
    for upload in uploads:
        response = client.get_object(Bucket=bucket, Key=upload.key)
        metadata = response.get("Metadata")
        if not isinstance(metadata, dict) or metadata.get("sha256") != upload.sha256:
            raise ValueError(f"R2 checksum metadata mismatch for {upload.key}")
        target = destination_dir / upload.key
        target.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        size_bytes = 0
        body = response.get("Body")
        if not hasattr(body, "read"):
            raise ValueError(f"R2 download body missing for {upload.key}")
        with target.open("wb") as handle:
            while True:
                chunk = body.read(1024 * 1024)
                if not chunk:
                    break
                if not isinstance(chunk, (bytes, bytearray)):
                    raise ValueError(f"R2 download body yielded a non-bytes chunk for {upload.key}")
                handle.write(chunk)
                digest.update(chunk)
                size_bytes += len(chunk)
        if size_bytes != upload.size_bytes or digest.hexdigest() != upload.sha256:
            raise ValueError(f"R2 downloaded object mismatch for {upload.key}")
        downloaded.append(
            {
                "key": upload.key,
                "size_bytes": size_bytes,
                "sha256": upload.sha256,
                "destination": str(target),
            }
        )
    return downloaded


def verify_local_round_trip(
    uploads: Iterable[R2Upload],
    *,
    destination_dir: Path,
) -> list[dict[str, object]]:
    if not destination_dir.is_dir():
        raise ValueError(f"download destination must be a directory: {destination_dir}")

    verified = []
    for upload in uploads:
        target = destination_dir / upload.key
        if not target.is_file():
            raise ValueError(f"downloaded artifact missing for {upload.key}")
        size_bytes = target.stat().st_size
        sha256 = _sha256_file(target)
        if size_bytes != upload.size_bytes or sha256 != upload.sha256:
            raise ValueError(f"downloaded artifact mismatch for {upload.key}")
        verified.append(
            {
                "key": upload.key,
                "size_bytes": size_bytes,
                "sha256": sha256,
                "destination": str(target),
            }
        )
    return verified


def _normalize_prefix(value: str) -> str:
    prefix = value.strip("/")
    if not prefix or any(part in {"", ".", ".."} for part in prefix.split("/")):
        raise ValueError("key prefix must be a non-empty relative path")
    return prefix


def _matches_remote_object(client: R2ObjectClient, bucket: str, upload: R2Upload) -> bool:
    try:
        head = client.head_object(Bucket=bucket, Key=upload.key)
    except Exception:
        return False
    metadata = head.get("Metadata")
    return (
        int(head.get("ContentLength", -1)) == upload.size_bytes
        and isinstance(metadata, dict)
        and metadata.get("sha256") == upload.sha256
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
