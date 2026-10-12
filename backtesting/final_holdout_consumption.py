from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping

from backtesting.forecast import load_forecast_config
from backtesting.forecast_final_holdout import FrozenContinuousFeatureArtifact

FINAL_HOLDOUT_CONSUMPTION_SCHEMA = "forecast_final_holdout_consumption_v1"
DEFAULT_FINAL_HOLDOUT_CONSUMPTION_PATH = Path(__file__).resolve().parent / "cache" / "final_holdout" / "consumption.json"


def build_consumption_context(
    artifact: FrozenContinuousFeatureArtifact,
    *,
    holdout_contract: Mapping[str, Any],
    provenance: Mapping[str, Any],
    bootstrap_samples: int,
) -> dict[str, Any]:
    final_holdout = _required_mapping(holdout_contract, "final_holdout")
    slot = {
        "holdout_start": str(holdout_contract["holdout_start"]),
        "label_version": str(holdout_contract["label_version"]),
        "feature_schema_version": str(holdout_contract["feature_schema_version"]),
        "final_holdout_from": final_holdout.get("from"),
        "final_holdout_through": final_holdout.get("through"),
        "final_holdout_fingerprint": final_holdout.get("fingerprint"),
    }
    selection_artifact = artifact.metadata()
    evaluation_config = {
        "bootstrap_samples": bootstrap_samples,
        "forecast_config": load_forecast_config(),
    }
    key_payload = {
        "model_version": artifact.model_version,
        "label_version": artifact.label_version,
        "feature_schema_version": artifact.feature_schema_version,
        "data_provenance_fingerprint": _fingerprint(provenance),
        "selection_artifact_fingerprint": _fingerprint(selection_artifact),
        "evaluation_config_fingerprint": _fingerprint(evaluation_config),
        "holdout_slot_key": _slot_key(slot),
    }
    return {
        "model_version": artifact.model_version,
        "label_version": artifact.label_version,
        "feature_schema_version": artifact.feature_schema_version,
        "data_provenance_fingerprint": key_payload["data_provenance_fingerprint"],
        "selection_artifact_fingerprint": key_payload["selection_artifact_fingerprint"],
        "evaluation_config_fingerprint": key_payload["evaluation_config_fingerprint"],
        "holdout_slot": slot,
        "holdout_slot_key": key_payload["holdout_slot_key"],
        "consumption_key": _fingerprint(key_payload),
    }


def reserve_consumption(path: Path, context: Mapping[str, Any]) -> None:
    registry = _load_registry(path)
    key = str(context["consumption_key"])
    slot_key = str(context["holdout_slot_key"])
    slot = _required_mapping(context, "holdout_slot")
    record = registry["consumption_keys"].get(key)
    if record is not None:
        raise ValueError(
            f"identical final-holdout consumption key already {record['status']}; explicit approval is required before retrying"
        )
    blocked = _matching_policy_block(registry["policy_blocks"], slot)
    if blocked is not None:
        raise ValueError(
            f"final holdout is already consumed by policy {blocked['source']}; explicit approval is required before reuse"
        )
    slot_record = registry["holdout_slots"].get(slot_key)
    if slot_record is not None:
        if slot_record["consumption_key"] == key:
            raise ValueError(
                f"identical final-holdout consumption key already {slot_record['status']}; explicit approval is required before retrying"
            )
        raise ValueError(
            "final holdout is already reserved or consumed by another artifact or evaluation configuration; "
            "explicit approval is required before reuse"
        )
    timestamp = _now()
    registry["consumption_keys"][key] = {
        "status": "reserved",
        "reserved_at": timestamp,
        "holdout_slot_key": slot_key,
        "context": dict(context),
    }
    registry["holdout_slots"][slot_key] = {
        "status": "reserved",
        "reserved_at": timestamp,
        "consumption_key": key,
        "slot": dict(slot),
    }
    _write_registry(path, registry)


def finalize_consumption(
    path: Path,
    context: Mapping[str, Any],
    *,
    report: Mapping[str, Any],
    report_path: Path,
) -> None:
    registry = _load_registry(path)
    key = str(context["consumption_key"])
    slot_key = str(context["holdout_slot_key"])
    if key not in registry["consumption_keys"] or slot_key not in registry["holdout_slots"]:
        raise ValueError("final holdout consumption must be reserved before it can be finalized")
    timestamp = _now()
    report_payload = json.dumps(report, sort_keys=True, separators=(",", ":"), default=str)
    report_sha256 = sha256(report_payload.encode("utf-8")).hexdigest()
    registry["consumption_keys"][key].update(
        {
            "status": "consumed",
            "consumed_at": timestamp,
            "report_sha256": report_sha256,
            "report_path": str(report_path),
        }
    )
    registry["holdout_slots"][slot_key].update(
        {
            "status": "consumed",
            "consumed_at": timestamp,
            "report_sha256": report_sha256,
            "report_path": str(report_path),
        }
    )
    _write_registry(path, registry)


def _load_registry(path: Path) -> dict[str, Any]:
    if path.exists():
        payload = json.loads(path.read_text(encoding="utf-8"))
    else:
        payload = {
            "schema_version": FINAL_HOLDOUT_CONSUMPTION_SCHEMA,
            "created_at": _now(),
            "policy_blocks": _default_policy_blocks(),
            "consumption_keys": {},
            "holdout_slots": {},
        }
        _write_registry(path, payload)
    if payload.get("schema_version") != FINAL_HOLDOUT_CONSUMPTION_SCHEMA:
        raise ValueError("unsupported final holdout consumption registry")
    for key in ("policy_blocks", "consumption_keys", "holdout_slots"):
        if key not in payload:
            raise ValueError(f"final holdout consumption registry is missing {key}")
    return payload


def _default_policy_blocks() -> list[dict[str, Any]]:
    return [
        {
            "status": "consumed",
            "source": "legacy_preexisting_2023_2024_final_holdout",
            "recorded_at": _now(),
            "match": {
                "holdout_start": "2023-01-01",
                "label_version": "next_open_low_v2",
                "feature_schema_version": None,
                "final_holdout_from": None,
                "final_holdout_through": None,
                "final_holdout_fingerprint": None,
            },
            "note": (
                "The 2023-2024 final holdout was consumed before STOCK-33 landed. "
                "Any reuse requires a separate explicit approval workflow."
            ),
        }
    ]


def _matching_policy_block(blocks: list[dict[str, Any]], slot: Mapping[str, Any]) -> dict[str, Any] | None:
    for block in blocks:
        match = _required_mapping(block, "match")
        if all(expected is None or slot.get(field) == expected for field, expected in match.items()):
            return block
    return None


def _slot_key(slot: Mapping[str, Any]) -> str:
    return _fingerprint(slot)


def _fingerprint(payload: Mapping[str, Any]) -> str:
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()


def _required_mapping(payload: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = payload.get(key)
    if not isinstance(value, Mapping):
        raise ValueError(f"missing mapping field: {key}")
    return value


def _write_registry(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
