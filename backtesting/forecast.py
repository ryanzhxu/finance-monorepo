from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from backtesting.walk_forward import WalkForwardFold, WalkForwardSettings, build_walk_forward_folds
from shared.config_loader import load_yaml_config, require_nested_keys

FORECAST_CONFIG_PATH = Path(__file__).resolve().parent / "config" / "forecast.yaml"
ForecastMode = Literal["upside_discovery", "downside_risk_scan"]
CalibrationStatus = Literal["unavailable", "validated"]
PositionTier = Literal["small_bet", "starter_bet", "larger_bet"]


class ForecastObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    as_of: date
    symbol: str = Field(min_length=1, max_length=20)
    signal_score: float = Field(ge=0, le=100)
    forward_return_3m: float
    max_drawdown_3m: float
    label_version: str = Field(default="close_v1", min_length=1)
    entry_date: date | None = None
    exit_date: date | None = None
    entry_price: float | None = Field(default=None, gt=0)
    exit_price: float | None = Field(default=None, gt=0)
    max_drawdown_date: date | None = None
    first_upside_threshold_date: date | None = None
    first_upside_threshold_sessions: int | None = Field(default=None, ge=0)
    first_downside_threshold_date: date | None = None
    first_downside_threshold_sessions: int | None = Field(default=None, ge=0)
    path_event_order: Literal[
        "upside_first",
        "downside_first",
        "same_session",
        "upside_only",
        "downside_only",
        "neither",
    ] | None = None
    feature_schema_version: str = Field(default="bucket_v1", min_length=1)
    feature_values: dict[str, float] = Field(default_factory=dict)
    market_regime: str | None = None

    @model_validator(mode="after")
    def validate_outcomes(self) -> ForecastObservation:
        if not np.isfinite(self.forward_return_3m) or not np.isfinite(self.max_drawdown_3m):
            raise ValueError("forecast outcomes must be finite")
        if any(not np.isfinite(value) for value in self.feature_values.values()):
            raise ValueError("forecast feature values must be finite")
        if self.market_regime is not None and self.market_regime not in {"risk_on", "neutral", "risk_off"}:
            raise ValueError("forecast market_regime must be risk_on, neutral, or risk_off")
        if (self.first_upside_threshold_date is None) != (self.first_upside_threshold_sessions is None):
            raise ValueError("upside threshold date and session must be recorded together")
        if (self.first_downside_threshold_date is None) != (self.first_downside_threshold_sessions is None):
            raise ValueError("downside threshold date and session must be recorded together")
        return self


class ForecastMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    out_of_sample_count: int = Field(ge=0)
    fold_count: int = Field(ge=0)
    upside_brier_score: float | None = Field(default=None, ge=0, le=1)
    upside_baseline_brier_score: float | None = Field(default=None, ge=0, le=1)
    downside_brier_score: float | None = Field(default=None, ge=0, le=1)
    downside_baseline_brier_score: float | None = Field(default=None, ge=0, le=1)
    upside_brier_improvement: float | None = None
    downside_brier_improvement: float | None = None


class ForecastContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_version: str
    mode: ForecastMode
    as_of: date
    trained_through: date | None
    data_coverage: dict[str, Any]
    calibration_status: CalibrationStatus
    metrics: ForecastMetrics
    expected_return_range: dict[str, float] | None = None
    upside_probability: float | None = Field(default=None, ge=0, le=1)
    downside_probability: float | None = Field(default=None, ge=0, le=1)
    event_definition: dict[str, Any]
    position_tier: PositionTier | None = None
    estimated_shares: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def enforce_fail_closed_numbers(self) -> ForecastContract:
        if self.calibration_status == "unavailable":
            numeric_fields = (self.expected_return_range, self.upside_probability, self.downside_probability)
            if any(value is not None for value in numeric_fields):
                raise ValueError("unavailable forecasts cannot contain numeric predictions")
            if self.position_tier is not None or self.estimated_shares is not None:
                raise ValueError("unavailable forecasts cannot contain position sizing")
        return self


@lru_cache
def load_forecast_config() -> dict[str, Any]:
    config = load_yaml_config(
        FORECAST_CONFIG_PATH,
        {
            "model_version",
            "horizon_sessions",
            "upside_return_threshold",
            "downside_drawdown_threshold",
            "bucket_count",
            "minimum_observations",
            "minimum_folds",
            "minimum_brier_improvement",
            "position_sizing",
        },
    )
    require_nested_keys(config, {"position_sizing": {"allocations", "larger_bet_upside_probability", "small_bet_downside_probability"}}, "forecast.yaml")
    return config


def _quantile(values: list[float], probability: float) -> float:
    if not values:
        raise ValueError("cannot calculate a quantile from no values")
    return round(float(np.quantile(np.asarray(values, dtype=float), probability)), 6)


def _bucket(score: float, bucket_count: int) -> int:
    return min(bucket_count - 1, max(0, int(score / 100 * bucket_count)))


def _smoothed_probability(events: int, total: int) -> float:
    return round((events + 1) / (total + 2), 6)


def _event_values(observations: Iterable[ForecastObservation], config: dict[str, Any]) -> tuple[list[int], list[int]]:
    upside_threshold = float(config["upside_return_threshold"])
    downside_threshold = float(config["downside_drawdown_threshold"])
    upside = [int(item.forward_return_3m >= upside_threshold) for item in observations]
    downside = [int(item.max_drawdown_3m <= downside_threshold) for item in observations]
    return upside, downside


def _bucket_prediction(
    observations: list[ForecastObservation],
    score: float,
    config: dict[str, Any],
) -> tuple[float, float, dict[str, float]]:
    return _bucket_predictions(observations, config)[_bucket(score, int(config["bucket_count"]))]


def _bucket_predictions(
    observations: list[ForecastObservation],
    config: dict[str, Any],
) -> dict[int, tuple[float, float, dict[str, float]]]:
    bucket_count = int(config["bucket_count"])
    grouped: dict[int, list[ForecastObservation]] = {bucket: [] for bucket in range(bucket_count)}
    for item in observations:
        grouped[_bucket(item.signal_score, bucket_count)].append(item)
    return {
        bucket: _prediction_for_observations(grouped[bucket] or observations, config)
        for bucket in range(bucket_count)
    }


def _prediction_for_observations(
    observations: list[ForecastObservation],
    config: dict[str, Any],
) -> tuple[float, float, dict[str, float]]:
    upside, downside = _event_values(observations, config)
    returns = [item.forward_return_3m for item in observations]
    return (
        _smoothed_probability(sum(upside), len(upside)),
        _smoothed_probability(sum(downside), len(downside)),
        {"p10": _quantile(returns, 0.10), "p50": _quantile(returns, 0.50), "p90": _quantile(returns, 0.90)},
    )


def _brier(predictions: list[float], outcomes: list[int]) -> float | None:
    if not predictions:
        return None
    return round(float(np.mean((np.asarray(predictions) - np.asarray(outcomes)) ** 2)), 6)


def _fold_test_observations(observations: list[ForecastObservation], fold: WalkForwardFold) -> tuple[list[ForecastObservation], list[ForecastObservation]]:
    training = [item for item in observations if item.as_of <= fold.train_end.date()]
    testing = [item for item in observations if fold.test_start.date() <= item.as_of <= fold.test_end.date()]
    return training, testing


class CalibratedForecastModel:
    def __init__(
        self,
        observations: list[ForecastObservation],
        folds: list[WalkForwardFold],
        metrics: ForecastMetrics,
        status: CalibrationStatus,
        config: dict[str, Any],
        model_version: str,
        point_in_time_certified: bool,
    ) -> None:
        self.observations = observations
        self.folds = folds
        self.metrics = metrics
        self.status = status
        self.config = config
        self.model_version = model_version
        self.point_in_time_certified = point_in_time_certified

    def predict(
        self,
        *,
        mode: ForecastMode,
        as_of: date,
        signal_score: float,
        capital: float | None = None,
        current_price: float | None = None,
    ) -> ForecastContract:
        trained_through = max((item.as_of for item in self.observations), default=None)
        coverage = {
            "observation_count": len(self.observations),
            "symbol_count": len({item.symbol for item in self.observations}),
            "from": min((item.as_of for item in self.observations), default=None),
            "through": trained_through,
            "point_in_time_certified": self.point_in_time_certified,
            "label_version": self.observations[0].label_version if self.observations else None,
        }
        event_definition = {
            "horizon_sessions": int(self.config["horizon_sessions"]),
            "upside": f"forward_return_3m >= {float(self.config['upside_return_threshold']):.2%}",
            "downside": f"max_drawdown_3m <= {float(self.config['downside_drawdown_threshold']):.2%}",
        }
        if self.status != "validated":
            return ForecastContract(
                model_version=self.model_version,
                mode=mode,
                as_of=as_of,
                trained_through=trained_through,
                data_coverage=coverage,
                calibration_status="unavailable",
                metrics=self.metrics,
                event_definition=event_definition,
            )

        upside_probability, downside_probability, expected_return_range = _bucket_prediction(
            self.observations,
            signal_score,
            self.config,
        )
        tier = _position_tier(upside_probability, downside_probability, self.config)
        estimated_shares = estimate_shares(capital, current_price, tier, self.config)
        return ForecastContract(
            model_version=self.model_version,
            mode=mode,
            as_of=as_of,
            trained_through=trained_through,
            data_coverage=coverage,
            calibration_status="validated",
            metrics=self.metrics,
            expected_return_range=expected_return_range,
            upside_probability=upside_probability,
            downside_probability=downside_probability,
            event_definition=event_definition,
            position_tier=tier,
            estimated_shares=estimated_shares,
        )


def fit_forecast_model(
    observations: Iterable[ForecastObservation],
    *,
    walk_forward: WalkForwardSettings | None = None,
    point_in_time_certified: bool = True,
) -> CalibratedForecastModel:
    config = load_forecast_config()
    normalized = sorted(list(observations), key=lambda item: (item.as_of, item.symbol))
    label_versions = {item.label_version for item in normalized}
    if len(label_versions) > 1:
        raise ValueError("forecast observations must use one label version per model run")
    label_version = next(iter(label_versions), "close_v1")
    settings = walk_forward or WalkForwardSettings()
    folds = build_walk_forward_folds(
        [datetime.combine(item.as_of, datetime.min.time()) for item in normalized],
        settings,
    )
    fold_dates = {fold.test_start.date(): fold for fold in folds}
    upside_predictions: list[float] = []
    downside_predictions: list[float] = []
    upside_outcomes: list[int] = []
    downside_outcomes: list[int] = []
    baseline_upside_predictions: list[float] = []
    baseline_downside_predictions: list[float] = []
    for fold in folds:
        training, testing = _fold_test_observations(normalized, fold)
        if not training:
            continue
        upside, downside = _event_values(training, config)
        base_upside = _smoothed_probability(sum(upside), len(upside))
        base_downside = _smoothed_probability(sum(downside), len(downside))
        predictions_by_bucket = _bucket_predictions(training, config)
        for item in testing:
            prediction = predictions_by_bucket[_bucket(item.signal_score, int(config["bucket_count"]))]
            upside_predictions.append(prediction[0])
            downside_predictions.append(prediction[1])
            upside_outcomes.append(int(item.forward_return_3m >= float(config["upside_return_threshold"])))
            downside_outcomes.append(int(item.max_drawdown_3m <= float(config["downside_drawdown_threshold"])))
            baseline_upside_predictions.append(base_upside)
            baseline_downside_predictions.append(base_downside)

    metrics = ForecastMetrics(
        out_of_sample_count=len(upside_predictions),
        fold_count=len(fold_dates),
        upside_brier_score=_brier(upside_predictions, upside_outcomes),
        upside_baseline_brier_score=_brier(baseline_upside_predictions, upside_outcomes),
        downside_brier_score=_brier(downside_predictions, downside_outcomes),
        downside_baseline_brier_score=_brier(baseline_downside_predictions, downside_outcomes),
    )
    metrics = metrics.model_copy(
        update={
            "upside_brier_improvement": _brier_improvement(metrics.upside_baseline_brier_score, metrics.upside_brier_score),
            "downside_brier_improvement": _brier_improvement(metrics.downside_baseline_brier_score, metrics.downside_brier_score),
        }
    )
    minimum_observations = int(config["minimum_observations"])
    minimum_folds = int(config["minimum_folds"])
    minimum_brier_improvement = float(config["minimum_brier_improvement"])
    status: CalibrationStatus = "validated" if (
        point_in_time_certified
        and
        metrics.out_of_sample_count >= minimum_observations
        and metrics.fold_count >= minimum_folds
        and metrics.upside_brier_score is not None
        and metrics.downside_brier_score is not None
        and metrics.upside_baseline_brier_score is not None
        and metrics.downside_baseline_brier_score is not None
        and metrics.upside_brier_improvement is not None
        and metrics.downside_brier_improvement is not None
        and metrics.upside_brier_improvement >= minimum_brier_improvement
        and metrics.downside_brier_improvement >= minimum_brier_improvement
    ) else "unavailable"
    return CalibratedForecastModel(
        normalized,
        folds,
        metrics,
        status,
        config,
        model_version=f"{str(config['model_version'])}_{label_version}",
        point_in_time_certified=point_in_time_certified,
    )


def _brier_improvement(baseline: float | None, model: float | None) -> float | None:
    if baseline is None or model is None:
        return None
    return round(baseline - model, 6)


def _position_tier(upside_probability: float, downside_probability: float, config: dict[str, Any]) -> PositionTier:
    sizing = config["position_sizing"]
    if downside_probability >= float(sizing["small_bet_downside_probability"]):
        return "small_bet"
    if upside_probability >= float(sizing["larger_bet_upside_probability"]):
        return "larger_bet"
    return "starter_bet"


def estimate_shares(
    capital: float | None,
    current_price: float | None,
    tier: PositionTier | None,
    config: dict[str, Any] | None = None,
) -> int | None:
    if capital is None or current_price is None or tier is None or capital <= 0 or current_price <= 0:
        return None
    config = config or load_forecast_config()
    allocation = float(config["position_sizing"]["allocations"][tier])
    return max(0, int((capital * allocation) // current_price))
