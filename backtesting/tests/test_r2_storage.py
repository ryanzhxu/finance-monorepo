import io
import sys
from pathlib import Path

import pytest

from backtesting.r2_storage import (
    R2StorageSettings,
    build_upload_plan,
    build_upload_plan_for_files,
    create_r2_client,
    download_verified_plan,
    upload_plan,
    upload_verified_plan,
    verify_local_round_trip,
)


def test_r2_settings_require_all_credentials() -> None:
    with pytest.raises(ValueError, match="R2_SECRET_ACCESS_KEY"):
        R2StorageSettings.from_environment({"R2_ACCOUNT_ID": "account", "R2_ACCESS_KEY_ID": "access"})


def test_r2_settings_always_use_the_private_research_bucket() -> None:
    settings = R2StorageSettings.from_environment(
        {
            "R2_ACCOUNT_ID": "account",
            "R2_ACCESS_KEY_ID": "access",
            "R2_SECRET_ACCESS_KEY": "secret",
            "R2_BUCKET": "wrong-bucket",
        }
    )

    assert settings.bucket == "finance-research-data"


def test_r2_client_uses_bounded_network_timeouts(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeBoto3:
        @staticmethod
        def client(*args: object, **kwargs: object) -> object:
            assert args == ("s3",)
            captured.update(kwargs)
            return object()

    monkeypatch.setitem(sys.modules, "boto3", FakeBoto3())

    create_r2_client(R2StorageSettings(account_id="account", access_key_id="access", secret_access_key="secret"))

    config = captured["config"]
    assert config.connect_timeout == 10
    assert config.read_timeout == 60


def test_upload_plan_preserves_relative_keys_and_checksums(tmp_path: Path) -> None:
    source = tmp_path / "dataset"
    nested = source / "reports"
    nested.mkdir(parents=True)
    (source / "manifest.json").write_text("{}", encoding="utf-8")
    (nested / "result.json").write_text('{"ok": true}', encoding="utf-8")

    plan = build_upload_plan(source, "reports/forecast/run-1")

    assert [item.key for item in plan] == [
        "reports/forecast/run-1/manifest.json",
        "reports/forecast/run-1/reports/result.json",
    ]
    assert all(len(item.sha256) == 64 for item in plan)


def test_upload_plan_rejects_unsafe_prefix(tmp_path: Path) -> None:
    source = tmp_path / "input.json"
    source.write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="key prefix"):
        build_upload_plan(source, "reports/../private")


def test_upload_plan_rejects_a_symlink_source(tmp_path: Path) -> None:
    target = tmp_path / "target.json"
    target.write_text("{}", encoding="utf-8")
    source = tmp_path / "linked.json"
    source.symlink_to(target)

    with pytest.raises(ValueError, match="symlink"):
        build_upload_plan(source, "reports/run-1")


def test_upload_plan_uses_private_bucket_client(tmp_path: Path) -> None:
    source = tmp_path / "manifest.json"
    source.write_text("{}", encoding="utf-8")
    calls: list[dict[str, object]] = []

    class Client:
        def put_object(self, **kwargs: object) -> None:
            calls.append(kwargs)

    uploaded = upload_plan(Client(), "finance-research-data", build_upload_plan(source, "manifests/run-1"))

    assert uploaded[0]["key"] == "manifests/run-1/manifest.json"
    assert calls[0]["Bucket"] == "finance-research-data"
    assert calls[0]["Metadata"] == {"sha256": uploaded[0]["sha256"]}


def test_verified_upload_checks_head_metadata_and_skips_matching_object(tmp_path: Path) -> None:
    source = tmp_path / "manifest.json"
    source.write_text("{}", encoding="utf-8")
    objects: dict[str, dict[str, object]] = {}

    class Client:
        def put_object(self, **kwargs: object) -> None:
            objects[str(kwargs["Key"])] = {
                "ContentLength": len(kwargs["Body"].read()),
                "Metadata": kwargs["Metadata"],
            }

        def head_object(self, **kwargs: object) -> dict[str, object]:
            if str(kwargs["Key"]) not in objects:
                raise ValueError("missing")
            return objects[str(kwargs["Key"])]

        def list_objects_v2(self, **kwargs: object) -> dict[str, object]:
            return {"Contents": [{"Size": item["ContentLength"]} for item in objects.values()], "IsTruncated": False}

    client = Client()
    plan = build_upload_plan_for_files([(source, "manifests/run-1/manifest.json")])

    first = upload_verified_plan(client, "finance-research-data", plan, storage_limit_bytes=100)
    second = upload_verified_plan(client, "finance-research-data", plan, storage_limit_bytes=100)

    assert len(first) == 1
    assert second == []


def test_verified_upload_stops_before_storage_limit(tmp_path: Path) -> None:
    source = tmp_path / "input.json"
    source.write_text("{}", encoding="utf-8")

    class Client:
        def head_object(self, **kwargs: object) -> dict[str, object]:
            raise ValueError("missing")

        def list_objects_v2(self, **kwargs: object) -> dict[str, object]:
            return {"Contents": [{"Size": 99}], "IsTruncated": False}

        def put_object(self, **kwargs: object) -> None:
            raise AssertionError("must not upload")

    with pytest.raises(ValueError, match="storage guard"):
        upload_verified_plan(Client(), "finance-research-data", build_upload_plan_for_files([(source, "reports/input.json")]), storage_limit_bytes=100)


def test_verified_download_restores_matching_private_artifact(tmp_path: Path) -> None:
    source = tmp_path / "report.json"
    source.write_text('{"ok": true}', encoding="utf-8")
    plan = build_upload_plan_for_files([(source, "reports/run-1/report.json")])
    upload = plan[0]

    class Client:
        def get_object(self, **kwargs: object) -> dict[str, object]:
            assert kwargs == {"Bucket": "finance-research-data", "Key": upload.key}
            return {
                "Metadata": {"sha256": upload.sha256},
                "Body": io.BytesIO(source.read_bytes()),
            }

    downloaded = download_verified_plan(
        Client(),
        "finance-research-data",
        plan,
        destination_dir=tmp_path / "downloads",
    )

    restored = tmp_path / "downloads" / "reports" / "run-1" / "report.json"
    assert restored.read_text(encoding="utf-8") == '{"ok": true}'
    assert downloaded == [
        {
            "key": "reports/run-1/report.json",
            "size_bytes": source.stat().st_size,
            "sha256": upload.sha256,
            "destination": str(restored),
        }
    ]


def test_verified_download_rejects_checksum_mismatch(tmp_path: Path) -> None:
    source = tmp_path / "report.json"
    source.write_text('{"ok": true}', encoding="utf-8")
    plan = build_upload_plan_for_files([(source, "reports/run-1/report.json")])

    class Client:
        def get_object(self, **kwargs: object) -> dict[str, object]:
            return {
                "Metadata": {"sha256": "0" * 64},
                "Body": io.BytesIO(source.read_bytes()),
            }

    with pytest.raises(ValueError, match="checksum metadata mismatch"):
        download_verified_plan(
            Client(),
            "finance-research-data",
            plan,
            destination_dir=tmp_path / "downloads",
        )


def test_local_round_trip_verifies_downloaded_artifacts_without_network(tmp_path: Path) -> None:
    source = tmp_path / "report.json"
    source.write_text('{"ok": true}', encoding="utf-8")
    plan = build_upload_plan_for_files([(source, "reports/run-1/report.json")])

    downloaded = tmp_path / "downloads" / "reports" / "run-1" / "report.json"
    downloaded.parent.mkdir(parents=True, exist_ok=True)
    downloaded.write_bytes(source.read_bytes())

    verified = verify_local_round_trip(plan, destination_dir=tmp_path / "downloads")

    assert verified == [
        {
            "key": "reports/run-1/report.json",
            "size_bytes": source.stat().st_size,
            "sha256": plan[0].sha256,
            "destination": str(downloaded),
        }
    ]


def test_local_round_trip_rejects_mismatched_downloaded_artifact(tmp_path: Path) -> None:
    source = tmp_path / "report.json"
    source.write_text('{"ok": true}', encoding="utf-8")
    plan = build_upload_plan_for_files([(source, "reports/run-1/report.json")])

    downloaded = tmp_path / "downloads" / "reports" / "run-1" / "report.json"
    downloaded.parent.mkdir(parents=True, exist_ok=True)
    downloaded.write_text('{"ok": false}', encoding="utf-8")

    with pytest.raises(ValueError, match="downloaded artifact mismatch"):
        verify_local_round_trip(plan, destination_dir=tmp_path / "downloads")
