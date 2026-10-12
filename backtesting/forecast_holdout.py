"""Immutable outer-holdout contracts for fair forecast-model comparisons."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from hashlib import sha256
import json
from typing import Any

from backtesting.forecast import ForecastObservation, load_forecast_config

DEFAULT_FINAL_HOLDOUT_START = date(2023, 1, 1)
HOLDOUT_CONTRACT_SCHEMA = "forecast_outer_holdout_v1"


@dataclass(frozen=True)
class OuterHoldoutSplit:
    selection: tuple[ForecastObservation, ...]
    final_holdout: tuple[ForecastObservation, ...]
    excluded_boundary: tuple[ForecastObservation, ...]
    excluded_reasons: dict[str, int]
    holdout_start: date


def split_outer_holdout(
    observations: Iterable[ForecastObservation],
    *,
    holdout_start: date = DEFAULT_FINAL_HOLDOUT_START,
) -> OuterHoldoutSplit:
    """Keep cross-boundary labels out of both selection and final evaluation."""

    rows = tuple(sorted(observations, key=lambda item: (item.as_of, item.symbol)))
    _validate_schema(rows)
    selection: list[ForecastObservation] = []
    final_holdout: list[ForecastObservation] = []
    excluded_boundary: list[ForecastObservation] = []
    reasons: Counter[str] = Counter()
    for item in rows:
        if item.entry_date is None or item.exit_date is None:
            excluded_boundary.append(item)
            reasons["missing_executable_label_dates"] += 1
            continue
        if not item.as_of < item.entry_date <= item.exit_date:
            raise ValueError("holdout observations must use next-session entry and non-decreasing label dates")
        if item.exit_date < holdout_start:
            selection.append(item)
        elif item.as_of >= holdout_start:
            final_holdout.append(item)
        else:
            excluded_boundary.append(item)
            reasons["label_crosses_final_holdout_boundary"] += 1
    return OuterHoldoutSplit(
        selection=tuple(selection),
        final_holdout=tuple(final_holdout),
        excluded_boundary=tuple(excluded_boundary),
        excluded_reasons=dict(sorted(reasons.items())),
        holdout_start=holdout_start,
    )


def build_outer_holdout_contract(split: OuterHoldoutSplit) -> dict[str, Any]:
    """Describe the only artifacts that future baseline, ML, and DL runs may share."""

    all_rows = (*split.selection, *split.final_holdout, *split.excluded_boundary)
    _validate_schema(all_rows)
    label_version = all_rows[0].label_version if all_rows else None
    feature_schema_version = all_rows[0].feature_schema_version if all_rows else None
    ready = bool(split.selection and split.final_holdout)
    return {
        "schema_version": HOLDOUT_CONTRACT_SCHEMA,
        "status": "ready" if ready else "unavailable",
        "holdout_start": split.holdout_start.isoformat(),
        "label_version": label_version,
        "feature_schema_version": feature_schema_version,
        "horizon_sessions": int(load_forecast_config()["horizon_sessions"]),
        "selection": _partition_summary(split.selection),
        "final_holdout": _partition_summary(split.final_holdout),
        "excluded_boundary": {
            "observation_count": len(split.excluded_boundary),
            "reasons": split.excluded_reasons,
        },
        "shared_benchmark_contract": {
            "allowed_model_families": ["flat_baseline", "score_bucket", "l2_logistic", "deep_learning_challenger"],
            "selection_rule": "feature selection and hyperparameter selection may use selection only",
            "final_holdout_rule": "final holdout may be evaluated once after selection is frozen",
            "numeric_forecast_rule": "unavailable unless the model passes existing calibration and provenance gates",
        },
    }


def validate_candidate_holdout_contract(
    contract: dict[str, Any],
    candidate: dict[str, Any],
) -> None:
    """Reject a candidate that was evaluated against a different holdout artifact."""

    if contract.get("schema_version") != HOLDOUT_CONTRACT_SCHEMA:
        raise ValueError("unsupported outer holdout contract")
    required = {"model_family", "label_version", "feature_schema_version", "selection_fingerprint", "final_holdout_fingerprint"}
    missing = sorted(required.difference(candidate))
    if missing:
        raise ValueError(f"candidate holdout contract is missing: {', '.join(missing)}")
    if candidate["model_family"] not in contract["shared_benchmark_contract"]["allowed_model_families"]:
        raise ValueError("candidate model family is not permitted by the shared benchmark contract")
    for key in ("label_version", "feature_schema_version"):
        if candidate[key] != contract[key]:
            raise ValueError(f"candidate {key} does not match the outer holdout contract")
    for partition, key in (("selection", "selection_fingerprint"), ("final_holdout", "final_holdout_fingerprint")):
        if candidate[key] != contract[partition]["fingerprint"]:
            raise ValueError(f"candidate {key} does not match the outer holdout contract")


def _partition_summary(observations: tuple[ForecastObservation, ...]) -> dict[str, Any]:
    return {
        "observation_count": len(observations),
        "symbol_count": len({item.symbol for item in observations}),
        "from": min((item.as_of for item in observations), default=None),
        "through": max((item.as_of for item in observations), default=None),
        "fingerprint": _fingerprint(observations),
    }


def _fingerprint(observations: tuple[ForecastObservation, ...]) -> str:
    payload = [item.model_dump(mode="json") for item in observations]
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _validate_schema(observations: tuple[ForecastObservation, ...]) -> None:
    for field in ("label_version", "feature_schema_version"):
        values = {getattr(item, field) for item in observations}
        if len(values) > 1:
            raise ValueError(f"outer holdout requires one {field} per experiment")
