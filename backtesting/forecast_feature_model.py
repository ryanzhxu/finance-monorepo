from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import datetime
from hashlib import sha256
import json
from math import exp, log
from typing import Any

import numpy as np
from sklearn.dummy import DummyClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from backtesting.forecast import (
    CalibrationStatus,
    ForecastObservation,
    _brier,
    _brier_improvement,
    _bucket,
    _bucket_predictions,
    _event_values,
    _smoothed_probability,
    load_forecast_config,
)
from backtesting.forecast_features import CONTINUOUS_FEATURE_SCHEMA, load_forecast_feature_config
from backtesting.sec_fundamental_features import COMBINED_FEATURE_SCHEMA
from backtesting.walk_forward import WalkForwardFold, WalkForwardSettings, build_walk_forward_folds

FEATURE_MODEL_VERSION = "forecast_continuous_regime_v3_target_calibration_v1"
SUPPORTED_FEATURE_SCHEMAS = frozenset({CONTINUOUS_FEATURE_SCHEMA, COMBINED_FEATURE_SCHEMA})


@dataclass(frozen=True)
class FeatureForecastMetrics:
    out_of_sample_count: int
    fold_count: int
    upside_brier_score: float | None
    upside_flat_brier_score: float | None
    upside_bucket_brier_score: float | None
    upside_regime_flat_brier_score: float | None
    downside_brier_score: float | None
    downside_flat_brier_score: float | None
    downside_bucket_brier_score: float | None
    downside_regime_flat_brier_score: float | None
    upside_brier_improvement: float | None
    downside_brier_improvement: float | None
    upside_bucket_brier_improvement: float | None
    downside_bucket_brier_improvement: float | None
    upside_regime_flat_brier_improvement: float | None
    downside_regime_flat_brier_improvement: float | None


@dataclass
class ContinuousFeatureForecastModel:
    observations: list[ForecastObservation]
    folds: list[WalkForwardFold]
    feature_schema_version: str
    payload_feature_names: list[str]
    feature_names: list[str]
    metrics: FeatureForecastMetrics
    status: CalibrationStatus
    point_in_time_certified: bool
    diagnostics: dict[str, Any]


def fit_continuous_feature_model(
    observations: Iterable[ForecastObservation],
    *,
    walk_forward: WalkForwardSettings | None = None,
    point_in_time_certified: bool = False,
) -> ContinuousFeatureForecastModel:
    """Fit independent upside/downside models using train-only preprocessing per fold."""

    normalized = sorted(list(observations), key=lambda item: (item.as_of, item.symbol))
    payload_feature_names, feature_schema_version = _validate_observations(normalized)
    settings = walk_forward or WalkForwardSettings()
    folds = build_walk_forward_folds(
        [datetime.combine(item.as_of, datetime.min.time()) for item in normalized],
        settings,
    )
    forecast_config = load_forecast_config()
    feature_config = load_forecast_feature_config()
    feature_names = _select_model_feature_names(payload_feature_names, feature_config)
    all_results: list[_FoldResult] = []
    for fold in folds:
        result = _fit_fold(normalized, fold, feature_names, forecast_config, feature_config)
        if result is not None:
            all_results.append(result)

    metrics = _aggregate_metrics(all_results)
    status = _calibration_status(metrics, point_in_time_certified, forecast_config)
    diagnostics = _diagnostics(
        all_results,
        feature_schema_version,
        feature_names,
        metrics,
        status,
        point_in_time_certified,
    )
    return ContinuousFeatureForecastModel(
        observations=normalized,
        folds=folds,
        feature_schema_version=feature_schema_version,
        payload_feature_names=payload_feature_names,
        feature_names=feature_names,
        metrics=metrics,
        status=status,
        point_in_time_certified=point_in_time_certified,
        diagnostics=diagnostics,
    )


def build_continuous_feature_report(model: ContinuousFeatureForecastModel) -> dict[str, Any]:
    observations = model.observations
    return {
        "model_version": _model_version(model.feature_schema_version),
        "calibration_status": model.status,
        "label_version": observations[0].label_version if observations else None,
        "feature_schema_version": model.feature_schema_version,
        "feature_payload_names": model.payload_feature_names,
        "feature_names": model.feature_names,
        "trained_through": max((item.as_of for item in observations), default=None),
        "data_coverage": {
            "observation_count": len(observations),
            "symbol_count": len({item.symbol for item in observations}),
            "from": min((item.as_of for item in observations), default=None),
            "through": max((item.as_of for item in observations), default=None),
            "point_in_time_certified": model.point_in_time_certified,
        },
        "out_of_sample_metrics": asdict(model.metrics),
        "promotion_gate": {
            "minimum_brier_improvement": float(load_forecast_config()["minimum_brier_improvement"]),
            "requires_point_in_time_certified": True,
            "result": model.status,
        },
        "evaluation_protocol": _evaluation_protocol(model.folds),
    }


def _evaluation_protocol(folds: list[WalkForwardFold]) -> dict[str, Any]:
    """Freeze the exact walk-forward boundaries used for an experiment comparison."""

    fold_boundaries = [
        {
            "train_start": fold.train_start.date().isoformat(),
            "train_end": fold.train_end.date().isoformat(),
            "validation_start": fold.validation_start.date().isoformat(),
            "validation_end": fold.validation_end.date().isoformat(),
            "test_start": fold.test_start.date().isoformat(),
            "test_end": fold.test_end.date().isoformat(),
        }
        for fold in folds
    ]
    canonical = json.dumps(fold_boundaries, sort_keys=True, separators=(",", ":"))
    return {
        "schema_version": "walk_forward_protocol_v1",
        "fold_count": len(fold_boundaries),
        "folds": fold_boundaries,
        "fingerprint": sha256(canonical.encode("utf-8")).hexdigest(),
    }


def _validate_observations(observations: list[ForecastObservation]) -> tuple[list[str], str]:
    label_versions = {item.label_version for item in observations}
    if len(label_versions) > 1:
        raise ValueError("forecast observations must use one label version per model run")
    schemas = {item.feature_schema_version for item in observations}
    if len(schemas) != 1 or not schemas <= SUPPORTED_FEATURE_SCHEMAS:
        supported = ", ".join(sorted(SUPPORTED_FEATURE_SCHEMAS))
        raise ValueError(f"continuous feature model requires only supported schemas: {supported}")
    feature_key_sets = {tuple(sorted(item.feature_values)) for item in observations}
    if len(feature_key_sets) != 1 or not feature_key_sets:
        raise ValueError("forecast observations must share one non-empty feature schema")
    feature_names = list(next(iter(feature_key_sets)))
    if not feature_names:
        raise ValueError("forecast observations must share one non-empty feature schema")
    if any(any(not np.isfinite(item.feature_values[name]) for name in feature_names) for item in observations):
        raise ValueError("forecast observations must contain only finite feature values")
    return feature_names, next(iter(schemas))


def _model_version(feature_schema_version: str) -> str:
    if feature_schema_version == CONTINUOUS_FEATURE_SCHEMA:
        return FEATURE_MODEL_VERSION
    return f"forecast_{feature_schema_version}"


def _select_model_feature_names(payload_feature_names: list[str], feature_config: dict[str, Any]) -> list[str]:
    """Apply a reviewed subset without changing the input-payload schema."""

    selection = feature_config.get("feature_selection")
    if not isinstance(selection, dict):
        raise ValueError("feature_selection config must be a mapping")
    excluded = selection.get("excluded_features")
    if not isinstance(excluded, list) or any(not isinstance(name, str) for name in excluded):
        raise ValueError("feature_selection.excluded_features must be a list of feature names")
    selected = [name for name in payload_feature_names if name not in excluded]
    if not selected:
        raise ValueError("feature_selection cannot exclude every feature")
    return selected


def _fit_fold(
    observations: list[ForecastObservation],
    fold: WalkForwardFold,
    feature_names: list[str],
    forecast_config: dict[str, Any],
    feature_config: dict[str, Any],
) -> _FoldResult | None:
    training = [item for item in observations if fold.train_start.date() <= item.as_of <= fold.train_end.date()]
    validation = [item for item in observations if fold.validation_start.date() <= item.as_of <= fold.validation_end.date()]
    testing = [item for item in observations if fold.test_start.date() <= item.as_of <= fold.test_end.date()]
    minimum = int(feature_config["logistic_regression"]["minimum_training_observations"])
    if len(training) < minimum or not validation or not testing:
        return None

    train_x = _feature_matrix(training, feature_names)
    validation_x = _feature_matrix(validation, feature_names)
    test_x = _feature_matrix(testing, feature_names)
    train_upside, train_downside = _event_values(training, forecast_config)
    validation_upside, validation_downside = _event_values(validation, forecast_config)
    test_upside, test_downside = _event_values(testing, forecast_config)
    candidates = [float(value) for value in feature_config["logistic_regression"]["regularization_candidates"]]
    feature_weights = [float(value) for value in feature_config["probability_shrinkage"]["feature_model_weights"]]
    prior_sources = [str(value) for value in feature_config["probability_shrinkage"]["prior_sources"]]
    max_iterations = int(feature_config["logistic_regression"]["max_iterations"])
    validation_upside_priors = _prior_predictions(training, train_upside, validation)
    validation_downside_priors = _prior_predictions(training, train_downside, validation)
    upside_model, upside_c, upside_weight, upside_prior_source = _select_model(
        train_x, train_upside, validation_x, validation_upside, candidates, feature_weights, prior_sources, max_iterations, validation_upside_priors
    )
    downside_model, downside_c, downside_weight, downside_prior_source = _select_model(
        train_x, train_downside, validation_x, validation_downside, candidates, feature_weights, prior_sources, max_iterations, validation_downside_priors
    )
    calibration_config = feature_config["target_calibration"]
    validation_upside_predictions = _shrink_probabilities(
        _probabilities(upside_model, validation_x), validation_upside_priors[upside_prior_source], upside_weight
    )
    upside_temperature = _select_temperature(
        validation_upside,
        validation_upside_predictions,
        _temperature_candidates(calibration_config),
    )
    downside_regime_calibrations = _select_regime_calibrations(
        downside_model,
        validation_x,
        validation_downside,
        validation,
        validation_downside_priors,
        feature_weights,
        prior_sources,
        downside_weight,
        downside_prior_source,
        enabled=bool(calibration_config["downside_regime_blending"]),
    )
    test_upside_priors = _prior_predictions(training, train_upside, testing)
    test_downside_priors = _prior_predictions(training, train_downside, testing)
    upside_predictions = _temperature_scale(
        _shrink_probabilities(_probabilities(upside_model, test_x), test_upside_priors[upside_prior_source], upside_weight),
        upside_temperature,
    )
    downside_predictions = _apply_regime_calibrations(
        downside_model,
        test_x,
        testing,
        test_downside_priors,
        downside_regime_calibrations,
    )
    baseline_upside, baseline_downside = _flat_predictions(training, testing, forecast_config)
    bucket_upside, bucket_downside = _bucket_baseline_predictions(training, testing, forecast_config)
    return _FoldResult(
        fold=fold,
        test_observations=testing,
        upside_outcomes=test_upside,
        downside_outcomes=test_downside,
        upside_predictions=upside_predictions,
        downside_predictions=downside_predictions,
        flat_upside_predictions=baseline_upside,
        flat_downside_predictions=baseline_downside,
        bucket_upside_predictions=bucket_upside,
        bucket_downside_predictions=bucket_downside,
        regime_flat_upside_predictions=test_upside_priors["regime_flat"],
        regime_flat_downside_predictions=test_downside_priors["regime_flat"],
        upside_regularization=upside_c,
        downside_regularization=downside_c,
        upside_feature_model_weight=upside_weight,
        downside_feature_model_weight=downside_weight,
        upside_prior_source=upside_prior_source,
        downside_prior_source=downside_prior_source,
        upside_temperature=upside_temperature,
        downside_regime_calibrations=downside_regime_calibrations,
        upside_coefficients=_coefficients(upside_model, feature_names),
        downside_coefficients=_coefficients(downside_model, feature_names),
    )


def _select_model(
    train_x: np.ndarray,
    train_y: list[int],
    validation_x: np.ndarray,
    validation_y: list[int],
    candidates: list[float],
    feature_weights: list[float],
    prior_sources: list[str],
    max_iterations: int,
    validation_priors: dict[str, list[float]],
) -> tuple[Pipeline, float | None, float, str]:
    if len(set(train_y)) < 2:
        model = Pipeline([("imputer", SimpleImputer(strategy="median")), ("constant", DummyClassifier(strategy="prior"))])
        model.fit(train_x, train_y)
        return model, None, 0.0, "global_flat"
    best_model: Pipeline | None = None
    best_c: float | None = None
    best_weight = 0.0
    best_prior_source = "global_flat"
    best_score: float | None = None
    for regularization in candidates:
        candidate = _logistic_pipeline(regularization, max_iterations)
        candidate.fit(train_x, train_y)
        probabilities = _probabilities(candidate, validation_x)
        for prior_source in prior_sources:
            priors = validation_priors.get(prior_source)
            if priors is None:
                raise ValueError(f"unsupported probability prior source: {prior_source}")
            for feature_weight in feature_weights:
                score = float(brier_score_loss(validation_y, _shrink_probabilities(probabilities, priors, feature_weight)))
                if best_score is None or score < best_score or (
                    score == best_score and (feature_weight, regularization, prior_source) < (best_weight, best_c or regularization, best_prior_source)
                ):
                    best_model = candidate
                    best_c = regularization
                    best_weight = feature_weight
                    best_prior_source = prior_source
                    best_score = score
    if best_model is None:
        raise RuntimeError("no regularization candidate was available")
    return best_model, best_c, best_weight, best_prior_source


def _logistic_pipeline(regularization: float, max_iterations: int) -> Pipeline:
    return Pipeline(
        [
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
            ("classifier", LogisticRegression(C=regularization, solver="lbfgs", max_iter=max_iterations)),
        ]
    )


def _feature_matrix(observations: list[ForecastObservation], feature_names: list[str]) -> np.ndarray:
    return np.asarray([[item.feature_values[name] for name in feature_names] for item in observations], dtype=float)


def _probabilities(model: Pipeline, values: np.ndarray) -> list[float]:
    probabilities = model.predict_proba(values)
    classes = model.classes_
    if 1 not in classes:
        return [0.0] * len(values)
    index = int(np.where(classes == 1)[0][0])
    return [float(value) for value in probabilities[:, index]]


def _flat_predictions(
    training: list[ForecastObservation],
    testing: list[ForecastObservation],
    config: dict[str, Any],
) -> tuple[list[float], list[float]]:
    upside, downside = _event_values(training, config)
    return (
        [_smoothed_probability(sum(upside), len(upside))] * len(testing),
        [_smoothed_probability(sum(downside), len(downside))] * len(testing),
    )


def _prior_predictions(
    training: list[ForecastObservation],
    training_outcomes: list[int],
    predicted: list[ForecastObservation],
) -> dict[str, list[float]]:
    """Return train-only smoothed event rates for each observable market regime."""

    global_rate = _smoothed_probability(sum(training_outcomes), len(training_outcomes))
    outcomes_by_regime: dict[str, list[int]] = {}
    for observation, outcome in zip(training, training_outcomes, strict=True):
        outcomes_by_regime.setdefault(observation.market_regime, []).append(outcome)
    rates = {
        regime: _smoothed_probability(sum(outcomes), len(outcomes))
        for regime, outcomes in outcomes_by_regime.items()
    }
    return {
        "global_flat": [global_rate] * len(predicted),
        "regime_flat": [rates.get(observation.market_regime, global_rate) for observation in predicted],
    }


def _shrink_probabilities(model: list[float], priors: list[float], feature_weight: float) -> list[float]:
    if not 0.0 <= feature_weight <= 1.0:
        raise ValueError("feature model weight must be within [0, 1]")
    if len(model) != len(priors):
        raise ValueError("model and regime prior predictions must have the same length")
    return [feature_weight * probability + (1.0 - feature_weight) * prior for probability, prior in zip(model, priors, strict=True)]


def _temperature_candidates(config: dict[str, Any]) -> list[float]:
    candidates = config.get("upside_temperature_candidates")
    if not isinstance(candidates, list) or not candidates:
        raise ValueError("target_calibration.upside_temperature_candidates must be a non-empty list")
    values = [float(value) for value in candidates]
    if any(not np.isfinite(value) or value <= 0 for value in values):
        raise ValueError("target_calibration temperatures must be finite and positive")
    return values


def _temperature_scale(probabilities: list[float], temperature: float) -> list[float]:
    if temperature <= 0:
        raise ValueError("temperature must be positive")
    values: list[float] = []
    for probability in probabilities:
        clipped = min(max(probability, 1e-6), 1.0 - 1e-6)
        logit = log(clipped / (1.0 - clipped))
        values.append(1.0 / (1.0 + exp(-logit / temperature)))
    return values


def _select_temperature(outcomes: list[int], probabilities: list[float], candidates: list[float]) -> float:
    return min(
        (float(brier_score_loss(outcomes, _temperature_scale(probabilities, temperature))), temperature)
        for temperature in candidates
    )[1]


def _select_regime_calibrations(
    model: Pipeline,
    validation_x: np.ndarray,
    validation_outcomes: list[int],
    validation: list[ForecastObservation],
    validation_priors: dict[str, list[float]],
    feature_weights: list[float],
    prior_sources: list[str],
    fallback_weight: float,
    fallback_source: str,
    *,
    enabled: bool,
) -> dict[str, tuple[float, str]]:
    raw_predictions = _probabilities(model, validation_x)
    calibrations: dict[str, tuple[float, str]] = {}
    for regime in ("risk_on", "neutral", "risk_off"):
        indices = [index for index, row in enumerate(validation) if row.market_regime == regime]
        if not enabled or not indices:
            calibrations[regime] = (fallback_weight, fallback_source)
            continue
        best: tuple[float, float, str] | None = None
        for prior_source in prior_sources:
            priors = validation_priors[prior_source]
            for feature_weight in feature_weights:
                predictions = [feature_weight * raw_predictions[index] + (1.0 - feature_weight) * priors[index] for index in indices]
                candidate = (float(brier_score_loss([validation_outcomes[index] for index in indices], predictions)), feature_weight, prior_source)
                if best is None or candidate < best:
                    best = candidate
        if best is None:
            raise RuntimeError("no regime calibration candidate was available")
        calibrations[regime] = (best[1], best[2])
    return calibrations


def _apply_regime_calibrations(
    model: Pipeline,
    values: np.ndarray,
    observations: list[ForecastObservation],
    priors: dict[str, list[float]],
    calibrations: dict[str, tuple[float, str]],
) -> list[float]:
    raw_predictions = _probabilities(model, values)
    return [
        calibrations[observation.market_regime][0] * probability
        + (1.0 - calibrations[observation.market_regime][0]) * priors[calibrations[observation.market_regime][1]][index]
        for index, (observation, probability) in enumerate(zip(observations, raw_predictions, strict=True))
    ]


def _bucket_baseline_predictions(
    training: list[ForecastObservation],
    testing: list[ForecastObservation],
    config: dict[str, Any],
) -> tuple[list[float], list[float]]:
    predictions = _bucket_predictions(training, config)
    bucket_count = int(config["bucket_count"])
    return (
        [predictions[_bucket(item.signal_score, bucket_count)][0] for item in testing],
        [predictions[_bucket(item.signal_score, bucket_count)][1] for item in testing],
    )


def _coefficients(model: Pipeline, feature_names: list[str]) -> dict[str, float]:
    classifier = model.named_steps.get("classifier")
    if not isinstance(classifier, LogisticRegression):
        return {}
    return {name: round(float(value), 6) for name, value in zip(feature_names, classifier.coef_[0], strict=True)}


def _aggregate_metrics(results: list[_FoldResult]) -> FeatureForecastMetrics:
    upside_predictions = [value for result in results for value in result.upside_predictions]
    downside_predictions = [value for result in results for value in result.downside_predictions]
    upside_outcomes = [value for result in results for value in result.upside_outcomes]
    downside_outcomes = [value for result in results for value in result.downside_outcomes]
    flat_upside = [value for result in results for value in result.flat_upside_predictions]
    flat_downside = [value for result in results for value in result.flat_downside_predictions]
    bucket_upside = [value for result in results for value in result.bucket_upside_predictions]
    bucket_downside = [value for result in results for value in result.bucket_downside_predictions]
    regime_flat_upside = [value for result in results for value in result.regime_flat_upside_predictions]
    regime_flat_downside = [value for result in results for value in result.regime_flat_downside_predictions]
    upside_model = _brier(upside_predictions, upside_outcomes)
    downside_model = _brier(downside_predictions, downside_outcomes)
    upside_flat = _brier(flat_upside, upside_outcomes)
    downside_flat = _brier(flat_downside, downside_outcomes)
    upside_bucket = _brier(bucket_upside, upside_outcomes)
    downside_bucket = _brier(bucket_downside, downside_outcomes)
    upside_regime_flat = _brier(regime_flat_upside, upside_outcomes)
    downside_regime_flat = _brier(regime_flat_downside, downside_outcomes)
    return FeatureForecastMetrics(
        out_of_sample_count=len(upside_predictions),
        fold_count=len(results),
        upside_brier_score=upside_model,
        upside_flat_brier_score=upside_flat,
        upside_bucket_brier_score=upside_bucket,
        upside_regime_flat_brier_score=upside_regime_flat,
        downside_brier_score=downside_model,
        downside_flat_brier_score=downside_flat,
        downside_bucket_brier_score=downside_bucket,
        downside_regime_flat_brier_score=downside_regime_flat,
        upside_brier_improvement=_brier_improvement(upside_flat, upside_model),
        downside_brier_improvement=_brier_improvement(downside_flat, downside_model),
        upside_bucket_brier_improvement=_brier_improvement(upside_bucket, upside_model),
        downside_bucket_brier_improvement=_brier_improvement(downside_bucket, downside_model),
        upside_regime_flat_brier_improvement=_brier_improvement(upside_regime_flat, upside_model),
        downside_regime_flat_brier_improvement=_brier_improvement(downside_regime_flat, downside_model),
    )


def _calibration_status(metrics: FeatureForecastMetrics, certified: bool, config: dict[str, Any]) -> CalibrationStatus:
    minimum_improvement = float(config["minimum_brier_improvement"])
    return "validated" if (
        certified
        and metrics.out_of_sample_count >= int(config["minimum_observations"])
        and metrics.fold_count >= int(config["minimum_folds"])
        and metrics.upside_brier_improvement is not None
        and metrics.downside_brier_improvement is not None
        and metrics.upside_brier_improvement >= minimum_improvement
        and metrics.downside_brier_improvement >= minimum_improvement
    ) else "unavailable"


def _diagnostics(
    results: list[_FoldResult],
    feature_schema_version: str,
    feature_names: list[str],
    metrics: FeatureForecastMetrics,
    status: CalibrationStatus,
    certified: bool,
) -> dict[str, Any]:
    return {
        "schema_version": "forecast_continuous_regime_diagnostics_v3",
        "model_version": _model_version(feature_schema_version),
        "calibration_status": status,
        "point_in_time_certified": certified,
        "feature_schema_version": feature_schema_version,
        "feature_names": feature_names,
        "aggregate_metrics": asdict(metrics),
        "folds": [_fold_diagnostic(result) for result in results],
        "regimes": _regime_diagnostics(results),
    }


def _fold_diagnostic(result: _FoldResult) -> dict[str, Any]:
    upside = _target_diagnostic(
        result.upside_outcomes,
        result.upside_predictions,
        result.flat_upside_predictions,
        result.bucket_upside_predictions,
        result.regime_flat_upside_predictions,
        result.upside_regularization,
        result.upside_feature_model_weight,
        result.upside_prior_source,
        result.upside_coefficients,
    )
    upside["selected_temperature"] = result.upside_temperature
    downside = _target_diagnostic(
        result.downside_outcomes,
        result.downside_predictions,
        result.flat_downside_predictions,
        result.bucket_downside_predictions,
        result.regime_flat_downside_predictions,
        result.downside_regularization,
        result.downside_feature_model_weight,
        result.downside_prior_source,
        result.downside_coefficients,
    )
    downside["selected_regime_calibrations"] = {
        regime: {"feature_model_weight": weight, "prior_source": source}
        for regime, (weight, source) in result.downside_regime_calibrations.items()
    }
    return {
        "train_start": result.fold.train_start.date(),
        "train_end": result.fold.train_end.date(),
        "validation_start": result.fold.validation_start.date(),
        "validation_end": result.fold.validation_end.date(),
        "test_start": result.fold.test_start.date(),
        "test_end": result.fold.test_end.date(),
        "count": len(result.test_observations),
        "upside": upside,
        "downside": downside,
    }


def _regime_diagnostics(results: list[_FoldResult]) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    for regime in ("risk_on", "neutral", "risk_off"):
        selected = [(result, index) for result in results for index, item in enumerate(result.test_observations) if item.market_regime == regime]
        upside_outcomes = [result.upside_outcomes[index] for result, index in selected]
        downside_outcomes = [result.downside_outcomes[index] for result, index in selected]
        values.append(
            {
                "regime": regime,
                "count": len(selected),
                "upside": _target_diagnostic(
                    upside_outcomes,
                    [result.upside_predictions[index] for result, index in selected],
                    [result.flat_upside_predictions[index] for result, index in selected],
                    [result.bucket_upside_predictions[index] for result, index in selected],
                    [result.regime_flat_upside_predictions[index] for result, index in selected],
                    None,
                    None,
                    None,
                    {},
                ),
                "downside": _target_diagnostic(
                    downside_outcomes,
                    [result.downside_predictions[index] for result, index in selected],
                    [result.flat_downside_predictions[index] for result, index in selected],
                    [result.bucket_downside_predictions[index] for result, index in selected],
                    [result.regime_flat_downside_predictions[index] for result, index in selected],
                    None,
                    None,
                    None,
                    {},
                ),
            }
        )
    return values


def _target_diagnostic(
    outcomes: list[int],
    predictions: list[float],
    flat_predictions: list[float],
    bucket_predictions: list[float],
    regime_flat_predictions: list[float],
    regularization: float | None,
    feature_model_weight: float | None,
    prior_source: str | None,
    coefficients: dict[str, float],
) -> dict[str, Any]:
    model_brier = _brier(predictions, outcomes)
    flat_brier = _brier(flat_predictions, outcomes)
    bucket_brier = _brier(bucket_predictions, outcomes)
    regime_flat_brier = _brier(regime_flat_predictions, outcomes)
    return {
        "event_rate": round(sum(outcomes) / len(outcomes), 6) if outcomes else None,
        "predicted_probability": round(float(np.mean(predictions)), 6) if predictions else None,
        "model_brier": model_brier,
        "flat_brier": flat_brier,
        "bucket_brier": bucket_brier,
        "regime_flat_brier": regime_flat_brier,
        "improvement_over_flat": _brier_improvement(flat_brier, model_brier),
        "improvement_over_bucket": _brier_improvement(bucket_brier, model_brier),
        "improvement_over_regime_flat": _brier_improvement(regime_flat_brier, model_brier),
        "selected_regularization": regularization,
        "selected_feature_model_weight": feature_model_weight,
        "selected_prior_source": prior_source,
        "coefficients": coefficients,
    }


@dataclass(frozen=True)
class _FoldResult:
    fold: WalkForwardFold
    test_observations: list[ForecastObservation]
    upside_outcomes: list[int]
    downside_outcomes: list[int]
    upside_predictions: list[float]
    downside_predictions: list[float]
    flat_upside_predictions: list[float]
    flat_downside_predictions: list[float]
    bucket_upside_predictions: list[float]
    bucket_downside_predictions: list[float]
    regime_flat_upside_predictions: list[float]
    regime_flat_downside_predictions: list[float]
    upside_regularization: float | None
    downside_regularization: float | None
    upside_feature_model_weight: float | None
    downside_feature_model_weight: float | None
    upside_prior_source: str | None
    downside_prior_source: str | None
    upside_temperature: float | None
    downside_regime_calibrations: dict[str, tuple[float, str]]
    upside_coefficients: dict[str, float]
    downside_coefficients: dict[str, float]
