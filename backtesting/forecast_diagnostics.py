from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Iterable

from backtesting.forecast import (
    CalibratedForecastModel,
    ForecastObservation,
    _brier,
    _bucket,
    _bucket_predictions,
    _event_values,
    _fold_test_observations,
    _smoothed_probability,
)


@dataclass(frozen=True)
class _Prediction:
    fold_index: int
    score_bucket: int
    upside_prediction: float
    downside_prediction: float
    base_upside_prediction: float
    base_downside_prediction: float
    upside_outcome: int
    downside_outcome: int


def build_forecast_calibration_diagnostics(model: CalibratedForecastModel) -> dict[str, object]:
    """Summarize the exact out-of-sample predictions used by the model metrics."""

    fold_rows: dict[int, list[_Prediction]] = defaultdict(list)
    bucket_rows: dict[int, list[_Prediction]] = defaultdict(list)
    all_rows: list[_Prediction] = []
    bucket_count = int(model.config["bucket_count"])
    for row in _iter_predictions(model):
        fold_rows[row.fold_index].append(row)
        bucket_rows[row.score_bucket].append(row)
        all_rows.append(row)

    aggregate = _metric_summary(all_rows)
    reported = model.metrics
    expected = {
        "upside_brier_score": reported.upside_brier_score,
        "upside_baseline_brier_score": reported.upside_baseline_brier_score,
        "downside_brier_score": reported.downside_brier_score,
        "downside_baseline_brier_score": reported.downside_baseline_brier_score,
    }
    if {key: aggregate[key] for key in expected} != expected:
        raise ValueError("diagnostic aggregate does not match forecast model metrics")

    folds = []
    for index, fold in enumerate(model.folds):
        folds.append(
            {
                "fold_index": index,
                "train_start": fold.train_start.date(),
                "train_end": fold.train_end.date(),
                "test_start": fold.test_start.date(),
                "test_end": fold.test_end.date(),
                **_metric_summary(fold_rows[index]),
            }
        )
    buckets = [
        {"bucket": bucket, "range": _bucket_range(bucket, bucket_count), **_metric_summary(bucket_rows[bucket])}
        for bucket in range(bucket_count)
    ]
    return {
        "schema_version": "forecast_calibration_diagnostics_v1",
        "model_version": model.model_version,
        "calibration_status": model.status,
        "point_in_time_certified": model.point_in_time_certified,
        "label_version": model.observations[0].label_version if model.observations else None,
        "observation_count": len(model.observations),
        "out_of_sample": aggregate,
        "folds": folds,
        "score_buckets": buckets,
    }


def _iter_predictions(model: CalibratedForecastModel) -> Iterable[_Prediction]:
    normalized = model.observations
    config = model.config
    bucket_count = int(config["bucket_count"])
    for fold_index, fold in enumerate(model.folds):
        training, testing = _fold_test_observations(normalized, fold)
        if not training:
            continue
        upside, downside = _event_values(training, config)
        base_upside = _smoothed_probability(sum(upside), len(upside))
        base_downside = _smoothed_probability(sum(downside), len(downside))
        predictions_by_bucket = _bucket_predictions(training, config)
        for item in testing:
            score_bucket = _bucket(item.signal_score, bucket_count)
            prediction = predictions_by_bucket[score_bucket]
            yield _Prediction(
                fold_index=fold_index,
                score_bucket=score_bucket,
                upside_prediction=prediction[0],
                downside_prediction=prediction[1],
                base_upside_prediction=base_upside,
                base_downside_prediction=base_downside,
                upside_outcome=int(item.forward_return_3m >= float(config["upside_return_threshold"])),
                downside_outcome=int(item.max_drawdown_3m <= float(config["downside_drawdown_threshold"])),
            )


def _metric_summary(rows: list[_Prediction]) -> dict[str, float | int | None]:
    upside_outcomes = [item.upside_outcome for item in rows]
    downside_outcomes = [item.downside_outcome for item in rows]
    upside_predictions = [item.upside_prediction for item in rows]
    downside_predictions = [item.downside_prediction for item in rows]
    base_upside_predictions = [item.base_upside_prediction for item in rows]
    base_downside_predictions = [item.base_downside_prediction for item in rows]
    upside_brier = _brier(upside_predictions, upside_outcomes)
    downside_brier = _brier(downside_predictions, downside_outcomes)
    upside_base_brier = _brier(base_upside_predictions, upside_outcomes)
    downside_base_brier = _brier(base_downside_predictions, downside_outcomes)
    return {
        "count": len(rows),
        "upside_event_rate": _rate(upside_outcomes),
        "downside_event_rate": _rate(downside_outcomes),
        "upside_mean_prediction": _mean(upside_predictions),
        "downside_mean_prediction": _mean(downside_predictions),
        "upside_base_rate": _mean(base_upside_predictions),
        "downside_base_rate": _mean(base_downside_predictions),
        "upside_brier_score": upside_brier,
        "upside_baseline_brier_score": upside_base_brier,
        "downside_brier_score": downside_brier,
        "downside_baseline_brier_score": downside_base_brier,
        "upside_brier_improvement": _improvement(upside_base_brier, upside_brier),
        "downside_brier_improvement": _improvement(downside_base_brier, downside_brier),
    }


def _rate(values: list[int]) -> float | None:
    return round(sum(values) / len(values), 6) if values else None


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 6) if values else None


def _improvement(baseline: float | None, model: float | None) -> float | None:
    return round(baseline - model, 6) if baseline is not None and model is not None else None


def _bucket_range(bucket: int, bucket_count: int) -> dict[str, float]:
    width = 100 / bucket_count
    return {"minimum": round(bucket * width, 6), "maximum": round((bucket + 1) * width, 6)}
