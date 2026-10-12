"""Frozen selection training and one-time final-holdout scoring for V3."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from hashlib import sha256
import json
from typing import Any, Literal

import numpy as np
from sklearn.dummy import DummyClassifier
from sklearn.pipeline import Pipeline

from backtesting.forecast import (
    ForecastObservation,
    _brier,
    _brier_improvement,
    _event_values,
    load_forecast_config,
)
from backtesting.forecast_feature_model import (
    _bucket_baseline_predictions,
    _feature_matrix,
    _flat_predictions,
    _logistic_pipeline,
    _model_version,
    _prior_predictions,
    _probabilities,
    _select_model_feature_names,
    _shrink_probabilities,
    _temperature_scale,
    _validate_observations,
    fit_continuous_feature_model,
)
from backtesting.forecast_features import load_forecast_feature_config
from backtesting.walk_forward import WalkForwardSettings

FINAL_HOLDOUT_REPORT_SCHEMA = "forecast_final_holdout_report_v1"


@dataclass(frozen=True)
class FrozenTargetConfiguration:
    regularization: float | None
    feature_model_weight: float
    prior_source: Literal["global_flat", "regime_flat"]
    temperature: float
    regime_calibrations: dict[str, tuple[float, str]] | None
    selection_fold_count: int
    selection_vote_count: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "regularization": self.regularization,
            "feature_model_weight": self.feature_model_weight,
            "prior_source": self.prior_source,
            "temperature": self.temperature,
            "regime_calibrations": (
                {
                    regime: {"feature_model_weight": weight, "prior_source": source}
                    for regime, (weight, source) in self.regime_calibrations.items()
                }
                if self.regime_calibrations
                else None
            ),
            "selection_fold_count": self.selection_fold_count,
            "selection_vote_count": self.selection_vote_count,
        }


@dataclass
class FrozenContinuousFeatureArtifact:
    """A model fitted only from selection data, before final labels are scored."""

    model_version: str
    label_version: str
    feature_schema_version: str
    feature_names: list[str]
    holdout_start: date
    trained_through: date
    selection_fingerprint: str
    selection_observation_count: int
    selection_symbol_count: int
    selection_fold_count: int
    point_in_time_certified: bool
    upside_configuration: FrozenTargetConfiguration
    downside_configuration: FrozenTargetConfiguration
    upside_model: Pipeline
    downside_model: Pipeline
    selection_observations: list[ForecastObservation]
    selection_diagnostics: dict[str, Any]

    def metadata(self) -> dict[str, Any]:
        return {
            "model_version": self.model_version,
            "label_version": self.label_version,
            "feature_schema_version": self.feature_schema_version,
            "feature_names": self.feature_names,
            "holdout_start": self.holdout_start.isoformat(),
            "trained_through": self.trained_through.isoformat(),
            "selection_fingerprint": self.selection_fingerprint,
            "selection_observation_count": self.selection_observation_count,
            "selection_symbol_count": self.selection_symbol_count,
            "selection_fold_count": self.selection_fold_count,
            "point_in_time_certified": self.point_in_time_certified,
            "selected_configuration": {
                "upside": self.upside_configuration.as_dict(),
                "downside": self.downside_configuration.as_dict(),
            },
            "selection_protocol": self.selection_diagnostics["evaluation_protocol"],
        }


def fit_frozen_continuous_feature_artifact(
    selection_observations: Iterable[ForecastObservation],
    *,
    holdout_start: date,
    point_in_time_certified: bool,
    walk_forward: WalkForwardSettings | None = None,
) -> FrozenContinuousFeatureArtifact:
    """Choose V3 settings on selection data, then fit each target on all selection rows."""

    selection = sorted(list(selection_observations), key=lambda item: (item.as_of, item.symbol))
    if not selection:
        raise ValueError("final holdout requires selection observations")
    if any(item.as_of >= holdout_start or item.exit_date is None or item.exit_date >= holdout_start for item in selection):
        raise ValueError("selection observations must finish before the final holdout")
    payload_feature_names, feature_schema_version = _validate_observations(selection)
    feature_names = _select_model_feature_names(payload_feature_names, load_forecast_feature_config())
    selection_model = fit_continuous_feature_model(
        selection,
        walk_forward=walk_forward,
        point_in_time_certified=point_in_time_certified,
    )
    diagnostics = selection_model.diagnostics
    upside_configuration = _modal_configuration(diagnostics, "upside")
    downside_configuration = _modal_configuration(diagnostics, "downside")
    config = load_forecast_config()
    train_x = _feature_matrix(selection, feature_names)
    upside, downside = _event_values(selection, config)
    return FrozenContinuousFeatureArtifact(
        model_version=_model_version(feature_schema_version),
        label_version=selection[0].label_version,
        feature_schema_version=feature_schema_version,
        feature_names=feature_names,
        holdout_start=holdout_start,
        trained_through=max(item.as_of for item in selection),
        selection_fingerprint=forecast_observation_fingerprint(selection),
        selection_observation_count=len(selection),
        selection_symbol_count=len({item.symbol for item in selection}),
        selection_fold_count=len(diagnostics["folds"]),
        point_in_time_certified=point_in_time_certified,
        upside_configuration=upside_configuration,
        downside_configuration=downside_configuration,
        upside_model=_fit_target_model(train_x, upside, upside_configuration),
        downside_model=_fit_target_model(train_x, downside, downside_configuration),
        selection_observations=selection,
        selection_diagnostics={
            "evaluation_protocol": _selection_protocol(selection_model),
            "aggregate_metrics": diagnostics["aggregate_metrics"],
        },
    )


def score_final_holdout(
    artifact: FrozenContinuousFeatureArtifact,
    final_holdout_observations: Iterable[ForecastObservation],
    *,
    bootstrap_samples: int = 500,
) -> dict[str, Any]:
    """Score final labels without changing the frozen artifact or its configuration."""

    final_holdout = sorted(list(final_holdout_observations), key=lambda item: (item.as_of, item.symbol))
    _validate_final_holdout(artifact, final_holdout)
    if bootstrap_samples <= 0:
        raise ValueError("bootstrap_samples must be positive")
    config = load_forecast_config()
    final_x = _feature_matrix(final_holdout, artifact.feature_names)
    upside_outcomes, downside_outcomes = _event_values(final_holdout, config)
    upside_predictions = _target_predictions(artifact, artifact.upside_model, artifact.upside_configuration, final_holdout, final_x, upside_outcomes)
    downside_predictions = _target_predictions(artifact, artifact.downside_model, artifact.downside_configuration, final_holdout, final_x, downside_outcomes)
    flat_upside, flat_downside = _flat_predictions(artifact.selection_observations, final_holdout, config)
    bucket_upside, bucket_downside = _bucket_baseline_predictions(artifact.selection_observations, final_holdout, config)
    metrics = {
        "out_of_sample_count": len(final_holdout),
        "fold_count": 1,
        **_target_metrics("upside", upside_predictions, upside_outcomes, flat_upside, bucket_upside),
        **_target_metrics("downside", downside_predictions, downside_outcomes, flat_downside, bucket_downside),
    }
    minimum_improvement = float(config["minimum_brier_improvement"])
    both_targets_pass = all(
        isinstance(metrics[f"{target}_brier_improvement"], float)
        and metrics[f"{target}_brier_improvement"] >= minimum_improvement
        for target in ("upside", "downside")
    )
    selection_metrics = artifact.selection_diagnostics["aggregate_metrics"]
    selection_passed = all(
        isinstance(selection_metrics[f"{target}_brier_improvement"], float)
        and selection_metrics[f"{target}_brier_improvement"] >= minimum_improvement
        for target in ("upside", "downside")
    )
    available = (
        artifact.point_in_time_certified
        and len(final_holdout) >= int(config["minimum_observations"])
        and artifact.selection_fold_count >= int(config["minimum_folds"])
        and selection_passed
        and both_targets_pass
    )
    return {
        "schema_version": FINAL_HOLDOUT_REPORT_SCHEMA,
        "experimental": True,
        "model_version": artifact.model_version,
        "label_version": artifact.label_version,
        "feature_schema_version": artifact.feature_schema_version,
        "calibration_status": "validated" if available else "unavailable",
        "numeric_forecast_status": "available" if available else "unavailable",
        "trained_artifact": artifact.metadata(),
        "final_holdout": {
            "observation_count": len(final_holdout),
            "symbol_count": len({item.symbol for item in final_holdout}),
            "from": min(item.as_of for item in final_holdout).isoformat(),
            "through": max(item.as_of for item in final_holdout).isoformat(),
            "fingerprint": forecast_observation_fingerprint(final_holdout),
        },
        "data_coverage": {
            "selection_observation_count": artifact.selection_observation_count,
            "selection_symbol_count": artifact.selection_symbol_count,
            "final_holdout_observation_count": len(final_holdout),
            "final_holdout_symbol_count": len({item.symbol for item in final_holdout}),
            "point_in_time_certified": artifact.point_in_time_certified,
        },
        "out_of_sample_metrics": metrics,
        "calibration": {
            "upside": _calibration_summary(upside_predictions, upside_outcomes, flat_upside, bootstrap_samples),
            "downside": _calibration_summary(downside_predictions, downside_outcomes, flat_downside, bootstrap_samples),
        },
        "promotion_gate": {
            "minimum_brier_improvement": minimum_improvement,
            "requires_point_in_time_certified": True,
            "selection_targets_pass": selection_passed,
            "final_holdout_targets_pass": both_targets_pass,
            "result": "validated" if available else "unavailable",
        },
    }


def forecast_observation_fingerprint(observations: Iterable[ForecastObservation]) -> str:
    payload = [item.model_dump(mode="json") for item in observations]
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _modal_configuration(diagnostics: dict[str, Any], target: Literal["upside", "downside"]) -> FrozenTargetConfiguration:
    votes: Counter[tuple[float | None, float, str]] = Counter()
    temperature_votes: Counter[float] = Counter()
    regime_votes: dict[str, Counter[tuple[float, str]]] = {
        regime: Counter() for regime in ("risk_on", "neutral", "risk_off")
    }
    folds = diagnostics.get("folds", [])
    for fold in folds:
        values = fold.get(target, {})
        regularization = values.get("selected_regularization")
        weight = values.get("selected_feature_model_weight")
        prior_source = values.get("selected_prior_source")
        if isinstance(regularization, (int, float)) and isinstance(weight, (int, float)) and prior_source in {"global_flat", "regime_flat"}:
            votes[(float(regularization), float(weight), prior_source)] += 1
        if target == "upside" and isinstance(values.get("selected_temperature"), (int, float)):
            temperature_votes[float(values["selected_temperature"])] += 1
        if target == "downside" and isinstance(values.get("selected_regime_calibrations"), dict):
            for regime, calibration in values["selected_regime_calibrations"].items():
                if not isinstance(calibration, dict):
                    continue
                weight_value = calibration.get("feature_model_weight")
                source_value = calibration.get("prior_source")
                if regime in regime_votes and isinstance(weight_value, (int, float)) and source_value in {"global_flat", "regime_flat"}:
                    regime_votes[regime][(float(weight_value), source_value)] += 1
    if not votes:
        raise ValueError(f"selection diagnostics do not contain a usable {target} configuration")
    configuration, vote_count = min(
        votes.items(),
        key=lambda item: (-item[1], item[0][2], item[0][1], item[0][0] if item[0][0] is not None else -1.0),
    )
    regularization, weight, prior_source = configuration
    temperature = _modal_value(temperature_votes, default=1.0)
    regime_calibrations = (
        {regime: _modal_value(votes) for regime, votes in regime_votes.items() if votes}
        if target == "downside"
        else None
    )
    return FrozenTargetConfiguration(
        regularization=regularization,
        feature_model_weight=weight,
        prior_source=prior_source,
        temperature=temperature,
        regime_calibrations=regime_calibrations or None,
        selection_fold_count=len(folds),
        selection_vote_count=vote_count,
    )


def _modal_value(votes: Counter[Any], *, default: Any = None) -> Any:
    if not votes:
        if default is None:
            raise ValueError("selection diagnostics do not contain a usable calibration value")
        return default
    return min(votes.items(), key=lambda item: (-item[1], item[0]))[0]


def _fit_target_model(values: np.ndarray, outcomes: list[int], configuration: FrozenTargetConfiguration) -> Pipeline:
    if len(set(outcomes)) < 2:
        model = Pipeline([("constant", DummyClassifier(strategy="prior"))])
    else:
        if configuration.regularization is None:
            raise ValueError("logistic configuration requires a regularization value")
        model = _logistic_pipeline(configuration.regularization, _max_iterations())
    model.fit(values, outcomes)
    return model


def _target_predictions(
    artifact: FrozenContinuousFeatureArtifact,
    model: Pipeline,
    configuration: FrozenTargetConfiguration,
    final_holdout: list[ForecastObservation],
    final_x: np.ndarray,
    _outcomes: list[int],
) -> list[float]:
    training_outcomes = _event_values(artifact.selection_observations, load_forecast_config())
    target_index = 0 if model is artifact.upside_model else 1
    priors = _prior_predictions(artifact.selection_observations, training_outcomes[target_index], final_holdout)
    raw_predictions = _probabilities(model, final_x)
    if configuration.regime_calibrations:
        return [
            configuration.regime_calibrations[row.market_regime][0] * probability
            + (1.0 - configuration.regime_calibrations[row.market_regime][0])
            * priors[configuration.regime_calibrations[row.market_regime][1]][index]
            for index, (row, probability) in enumerate(zip(final_holdout, raw_predictions, strict=True))
        ]
    return _temperature_scale(
        _shrink_probabilities(raw_predictions, priors[configuration.prior_source], configuration.feature_model_weight),
        configuration.temperature,
    )


def _target_metrics(
    target: Literal["upside", "downside"],
    predictions: list[float],
    outcomes: list[int],
    flat_predictions: list[float],
    bucket_predictions: list[float],
) -> dict[str, float | None]:
    model_brier = _brier(predictions, outcomes)
    flat_brier = _brier(flat_predictions, outcomes)
    bucket_brier = _brier(bucket_predictions, outcomes)
    return {
        f"{target}_brier_score": model_brier,
        f"{target}_flat_brier_score": flat_brier,
        f"{target}_bucket_brier_score": bucket_brier,
        f"{target}_brier_improvement": _brier_improvement(flat_brier, model_brier),
        f"{target}_bucket_brier_improvement": _brier_improvement(bucket_brier, model_brier),
    }


def _calibration_summary(
    predictions: list[float],
    outcomes: list[int],
    flat_predictions: list[float],
    bootstrap_samples: int,
) -> dict[str, Any]:
    prediction_array = np.asarray(predictions, dtype=float)
    outcome_array = np.asarray(outcomes, dtype=float)
    flat_array = np.asarray(flat_predictions, dtype=float)
    return {
        "event_rate": round(float(outcome_array.mean()), 6),
        "mean_prediction": round(float(prediction_array.mean()), 6),
        "brier_confidence_interval_95": _bootstrap_interval((prediction_array - outcome_array) ** 2, bootstrap_samples),
        "improvement_confidence_interval_95": _bootstrap_interval(
            (flat_array - outcome_array) ** 2 - (prediction_array - outcome_array) ** 2,
            bootstrap_samples,
        ),
        "bins": _calibration_bins(prediction_array, outcome_array),
        "uncertainty_method": "deterministic nonparametric bootstrap, seed 0",
    }


def _bootstrap_interval(values: np.ndarray, samples: int) -> dict[str, float]:
    rng = np.random.default_rng(0)
    means = np.empty(samples, dtype=float)
    for index in range(samples):
        means[index] = float(rng.choice(values, size=len(values), replace=True).mean())
    return {
        "lower": round(float(np.quantile(means, 0.025)), 6),
        "upper": round(float(np.quantile(means, 0.975)), 6),
    }


def _calibration_bins(predictions: np.ndarray, outcomes: np.ndarray) -> list[dict[str, float | int]]:
    bins: list[dict[str, float | int]] = []
    for index in range(10):
        lower = index / 10
        upper = (index + 1) / 10
        mask = (predictions >= lower) & (predictions < upper if index < 9 else predictions <= upper)
        if not mask.any():
            continue
        bins.append(
            {
                "minimum": lower,
                "maximum": upper,
                "count": int(mask.sum()),
                "mean_prediction": round(float(predictions[mask].mean()), 6),
                "event_rate": round(float(outcomes[mask].mean()), 6),
            }
        )
    return bins


def _validate_final_holdout(artifact: FrozenContinuousFeatureArtifact, rows: list[ForecastObservation]) -> None:
    if not rows:
        raise ValueError("final holdout requires observations")
    if any(item.label_version != artifact.label_version or item.feature_schema_version != artifact.feature_schema_version for item in rows):
        raise ValueError("final holdout label or feature schema does not match the frozen artifact")
    payload_feature_names, feature_schema = _validate_observations(rows)
    feature_names = _select_model_feature_names(payload_feature_names, load_forecast_feature_config())
    if feature_schema != artifact.feature_schema_version:
        raise ValueError("final holdout label or feature schema does not match the frozen artifact")
    if feature_names != artifact.feature_names:
        raise ValueError("final holdout feature names do not match the frozen artifact")
    if any(item.as_of < artifact.holdout_start for item in rows):
        raise ValueError("final holdout contains selection-period observations")
    if any(item.entry_date is None or item.exit_date is None or item.as_of >= item.entry_date > item.exit_date for item in rows):
        raise ValueError("final holdout observations must use executable next-session labels")


def _selection_protocol(model: Any) -> dict[str, Any]:
    from backtesting.forecast_feature_model import build_continuous_feature_report

    return build_continuous_feature_report(model)["evaluation_protocol"]


def _max_iterations() -> int:
    from backtesting.forecast_features import load_forecast_feature_config

    return int(load_forecast_feature_config()["logistic_regression"]["max_iterations"])
