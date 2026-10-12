"""Immutable manifests and promotion decisions for offline forecast experiments."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from backtesting.forecast import load_forecast_config

EXPERIMENT_MANIFEST_SCHEMA = "forecast_experiment_manifest_v1"
PRIMARY_BRIER_METRICS = ("upside_brier_score", "downside_brier_score")


def build_experiment_manifest(
    report: Mapping[str, Any],
    *,
    name: str,
    hypothesis: str,
    observations_sha256: str,
    report_sha256: str,
) -> dict[str, Any]:
    """Record the immutable inputs needed to reproduce one offline model result."""

    if not name.strip() or not hypothesis.strip():
        raise ValueError("experiment name and hypothesis are required")
    metrics = _required_mapping(report, "out_of_sample_metrics")
    protocol = _required_mapping(report, "evaluation_protocol")
    data_coverage = _required_mapping(report, "data_coverage")
    promotion_gate = _required_mapping(report, "promotion_gate")
    _require_hash("observations_sha256", observations_sha256)
    _require_hash("report_sha256", report_sha256)
    _require_metrics(metrics)
    if not protocol.get("fingerprint"):
        raise ValueError("experiment report must include an evaluation protocol fingerprint")

    point_in_time_certified = bool(data_coverage.get("point_in_time_certified"))
    calibration_status = report.get("calibration_status")
    return {
        "schema_version": EXPERIMENT_MANIFEST_SCHEMA,
        "name": name,
        "hypothesis": hypothesis,
        "artifacts": {
            "observations_sha256": observations_sha256,
            "report_sha256": report_sha256,
        },
        "model": {
            "model_version": report.get("model_version"),
            "label_version": report.get("label_version"),
            "feature_schema_version": report.get("feature_schema_version"),
            "data_coverage": deepcopy(dict(data_coverage)),
            "evaluation_protocol": deepcopy(dict(protocol)),
        },
        "out_of_sample_metrics": {metric: metrics[metric] for metric in PRIMARY_BRIER_METRICS},
        "eligibility": {
            "calibration_status": calibration_status,
            "point_in_time_certified": point_in_time_certified,
            "forecast_eligible": calibration_status == "validated" and point_in_time_certified,
            "minimum_brier_improvement": promotion_gate.get("minimum_brier_improvement"),
        },
    }


def compare_challenger_to_champion(
    champion: Mapping[str, Any],
    challenger: Mapping[str, Any],
    *,
    minimum_brier_improvement: float | None = None,
) -> dict[str, Any]:
    """Promote only a certified challenger that wins both locked primary metrics."""

    _validate_manifest(champion)
    _validate_manifest(challenger)
    threshold = (
        float(minimum_brier_improvement)
        if minimum_brier_improvement is not None
        else float(load_forecast_config()["minimum_brier_improvement"])
    )
    if threshold < 0:
        raise ValueError("minimum brier improvement cannot be negative")

    compatibility_issues = _compatibility_issues(champion, challenger)
    if compatibility_issues:
        return _decision("retain", "incompatible_experiment_protocol", threshold, {}, compatibility_issues)
    if not challenger["eligibility"]["forecast_eligible"]:
        return _decision("retain", "challenger_is_not_forecast_eligible", threshold, {}, [])

    deltas = {
        metric: round(
            float(champion["out_of_sample_metrics"][metric]) - float(challenger["out_of_sample_metrics"][metric]),
            6,
        )
        for metric in PRIMARY_BRIER_METRICS
    }
    if all(delta >= threshold for delta in deltas.values()):
        return _decision("promote", "challenger_wins_both_primary_metrics", threshold, deltas, [])
    return _decision("retain", "challenger_does_not_win_both_primary_metrics", threshold, deltas, [])


def compare_selection_candidate_to_champion(
    champion: Mapping[str, Any],
    candidate: Mapping[str, Any],
    *,
    minimum_brier_improvement: float | None = None,
) -> dict[str, Any]:
    """Choose an offline selection champion without implying forecast promotion."""

    _validate_manifest(champion)
    _validate_manifest(candidate)
    threshold = (
        float(minimum_brier_improvement)
        if minimum_brier_improvement is not None
        else float(load_forecast_config()["minimum_brier_improvement"])
    )
    compatibility_issues = _compatibility_issues(champion, candidate)
    if compatibility_issues:
        return _selection_decision("retain", "incompatible_experiment_protocol", threshold, {}, compatibility_issues)
    deltas = {
        metric: round(
            float(champion["out_of_sample_metrics"][metric]) - float(candidate["out_of_sample_metrics"][metric]),
            6,
        )
        for metric in PRIMARY_BRIER_METRICS
    }
    if all(delta >= threshold for delta in deltas.values()):
        return _selection_decision("replace", "candidate_wins_both_primary_metrics", threshold, deltas, [])
    return _selection_decision("retain", "candidate_does_not_win_both_primary_metrics", threshold, deltas, [])


def _decision(
    decision: str,
    reason: str,
    threshold: float,
    brier_deltas: Mapping[str, float],
    compatibility_issues: list[str],
) -> dict[str, Any]:
    return {
        "schema_version": "forecast_champion_decision_v1",
        "decision": decision,
        "reason": reason,
        "minimum_brier_improvement": threshold,
        "brier_improvements_over_champion": dict(brier_deltas),
        "compatibility_issues": compatibility_issues,
    }


def _selection_decision(
    decision: str,
    reason: str,
    threshold: float,
    brier_deltas: Mapping[str, float],
    compatibility_issues: list[str],
) -> dict[str, Any]:
    return {
        "schema_version": "forecast_selection_champion_decision_v1",
        "decision": decision,
        "reason": reason,
        "minimum_brier_improvement": threshold,
        "brier_improvements_over_champion": dict(brier_deltas),
        "compatibility_issues": compatibility_issues,
        "numeric_forecast_promotion": "not_evaluated",
    }


def _compatibility_issues(champion: Mapping[str, Any], challenger: Mapping[str, Any]) -> list[str]:
    champion_model = champion["model"]
    challenger_model = challenger["model"]
    checks = {
        "label_version": (champion_model["label_version"], challenger_model["label_version"]),
        "data_coverage": (champion_model["data_coverage"], challenger_model["data_coverage"]),
        "evaluation_protocol": (
            champion_model["evaluation_protocol"]["fingerprint"],
            challenger_model["evaluation_protocol"]["fingerprint"],
        ),
    }
    return [name for name, (left, right) in checks.items() if left != right]


def _validate_manifest(manifest: Mapping[str, Any]) -> None:
    if manifest.get("schema_version") != EXPERIMENT_MANIFEST_SCHEMA:
        raise ValueError("unsupported experiment manifest")
    model = _required_mapping(manifest, "model")
    _required_mapping(model, "data_coverage")
    protocol = _required_mapping(model, "evaluation_protocol")
    if not protocol.get("fingerprint"):
        raise ValueError("experiment manifest is missing an evaluation protocol fingerprint")
    metrics = _required_mapping(manifest, "out_of_sample_metrics")
    _require_metrics(metrics)
    eligibility = _required_mapping(manifest, "eligibility")
    if "forecast_eligible" not in eligibility:
        raise ValueError("experiment manifest is missing forecast eligibility")


def _required_mapping(container: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = container.get(key)
    if not isinstance(value, Mapping):
        raise ValueError(f"experiment report is missing {key}")
    return value


def _require_metrics(metrics: Mapping[str, Any]) -> None:
    if any(metrics.get(metric) is None for metric in PRIMARY_BRIER_METRICS):
        raise ValueError("experiment report is missing primary brier metrics")


def _require_hash(name: str, value: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{name} must be a lowercase SHA-256 hex digest")
