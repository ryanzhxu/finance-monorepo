from __future__ import annotations

from collections import defaultdict
from statistics import median
from typing import Any

SUPPORTED_DIAGNOSTIC_SCHEMAS = frozenset(
    {
        "forecast_continuous_regime_diagnostics_v1",
        "forecast_continuous_regime_diagnostics_v2",
        "forecast_continuous_regime_diagnostics_v3",
    }
)


def build_continuous_feature_audit(diagnostics: dict[str, Any]) -> dict[str, Any]:
    """Summarize repeatable regime and coefficient evidence without refitting a model."""

    if diagnostics.get("schema_version") not in SUPPORTED_DIAGNOSTIC_SCHEMAS:
        raise ValueError("continuous feature audit requires continuous-regime diagnostics")
    folds = diagnostics.get("folds")
    regimes = diagnostics.get("regimes")
    if not isinstance(folds, list) or not isinstance(regimes, list):
        raise ValueError("continuous feature diagnostics must include folds and regimes")
    return {
        "schema_version": "forecast_continuous_feature_audit_v1",
        "model_version": diagnostics.get("model_version"),
        "calibration_status": diagnostics.get("calibration_status"),
        "promotion_decision": "block",
        "blockers": _blockers(diagnostics),
        "regimes": [_regime_audit(row) for row in regimes if isinstance(row, dict)],
        "fold_summary": _fold_summary(folds),
        "worst_folds": _worst_folds(folds),
        "coefficient_summary": _coefficient_summary(folds),
        "next_data_requirements": [
            "historical corporate-action availability as of each signal date",
            "historical universe membership including delisted securities",
            "source provenance that identifies the dataset version and coverage",
        ],
    }


def _blockers(diagnostics: dict[str, Any]) -> list[str]:
    metrics = diagnostics.get("aggregate_metrics", {})
    blockers: list[str] = []
    if diagnostics.get("point_in_time_certified") is not True:
        blockers.append("price provenance is not point-in-time certified")
    for target in ("upside", "downside"):
        improvement = metrics.get(f"{target}_brier_improvement")
        if not isinstance(improvement, (int, float)) or improvement < 0.001:
            blockers.append(f"{target} OOS Brier improvement is below the 0.001 promotion gate")
    return blockers


def _regime_audit(row: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {"regime": row.get("regime"), "count": row.get("count")}
    for target in ("upside", "downside"):
        values = row.get(target, {})
        improvement = values.get("improvement_over_flat") if isinstance(values, dict) else None
        summary[target] = {
            "event_rate": values.get("event_rate") if isinstance(values, dict) else None,
            "improvement_over_flat": improvement,
            "diagnosis": _diagnosis(improvement),
        }
    return summary


def _diagnosis(improvement: object) -> str:
    if not isinstance(improvement, (int, float)):
        return "insufficient_data"
    if improvement >= 0.001:
        return "meets_local_brier_gate_only"
    if improvement > 0:
        return "positive_but_below_gate"
    return "worse_than_flat_baseline"


def _fold_summary(folds: list[object]) -> dict[str, Any]:
    output: dict[str, Any] = {"fold_count": len(folds)}
    for target in ("upside", "downside"):
        improvements = [
            float(values["improvement_over_flat"])
            for fold in folds
            if isinstance(fold, dict)
            for values in [fold.get(target)]
            if isinstance(values, dict) and isinstance(values.get("improvement_over_flat"), (int, float))
        ]
        output[target] = {
            "positive_fold_count": sum(value > 0 for value in improvements),
            "gate_passing_fold_count": sum(value >= 0.001 for value in improvements),
            "worse_fold_count": sum(value < 0 for value in improvements),
            "median_improvement_over_flat": round(median(improvements), 6) if improvements else None,
        }
    return output


def _coefficient_summary(folds: list[object]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, dict[str, list[float]]] = {"upside": defaultdict(list), "downside": defaultdict(list)}
    for fold in folds:
        if not isinstance(fold, dict):
            continue
        for target in grouped:
            values = fold.get(target)
            coefficients = values.get("coefficients") if isinstance(values, dict) else None
            if not isinstance(coefficients, dict):
                continue
            for name, value in coefficients.items():
                if isinstance(name, str) and isinstance(value, (int, float)):
                    grouped[target][name].append(float(value))
    return {
        target: [
            {
                "feature": name,
                "fold_count": len(values),
                "median_coefficient": round(median(values), 6),
                "positive_fold_fraction": round(sum(value > 0 for value in values) / len(values), 6),
            }
            for name, values in sorted(features.items())
        ]
        for target, features in grouped.items()
    }


def _worst_folds(folds: list[object]) -> dict[str, list[dict[str, Any]]]:
    output: dict[str, list[dict[str, Any]]] = {}
    for target in ("upside", "downside"):
        candidates: list[dict[str, Any]] = []
        for fold in folds:
            if not isinstance(fold, dict):
                continue
            values = fold.get(target)
            improvement = values.get("improvement_over_flat") if isinstance(values, dict) else None
            if not isinstance(improvement, (int, float)):
                continue
            candidates.append(
                {
                    "test_start": fold.get("test_start"),
                    "test_end": fold.get("test_end"),
                    "count": fold.get("count"),
                    "improvement_over_flat": round(float(improvement), 6),
                    "model_brier": values.get("model_brier"),
                    "flat_brier": values.get("flat_brier"),
                }
            )
        output[target] = sorted(candidates, key=lambda item: item["improvement_over_flat"])[:5]
    return output
