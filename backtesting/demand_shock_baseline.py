from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from shared.enums import Direction

from analyst_service.core.persistence import PersistedAnalysis
from backtesting.evaluator import EvaluationReport, PriceLoader, evaluate_records, fetch_adjusted_close_history
from backtesting.historical_dataset import HistoricalFeatureSnapshot, load_historical_feature_snapshots
from backtesting.walk_forward import WalkForwardFold, WalkForwardSettings, build_walk_forward_folds
from screener_service.core.demand_shock import score_demand_shock_metrics
from screener_service.core.filters import apply_filters
from screener_service.core.settings import load_screener_config


@dataclass(frozen=True)
class DemandShockFoldReport:
    fold: WalkForwardFold
    candidate_count: int
    evaluation: EvaluationReport


@dataclass(frozen=True)
class DemandShockBaselineReport:
    folds: list[DemandShockFoldReport]
    evaluation: EvaluationReport


def run_demand_shock_baseline_from_file(
    path: Path,
    *,
    price_loader: PriceLoader | None = None,
    settings: WalkForwardSettings = WalkForwardSettings(),
    top_n: int = 10,
    benchmark_symbol: str = "SPY",
) -> DemandShockBaselineReport:
    return run_demand_shock_baseline(
        load_historical_feature_snapshots(path),
        price_loader=price_loader,
        settings=settings,
        top_n=top_n,
        benchmark_symbol=benchmark_symbol,
    )


def run_demand_shock_baseline(
    snapshots: Iterable[HistoricalFeatureSnapshot],
    *,
    price_loader: PriceLoader | None = None,
    settings: WalkForwardSettings = WalkForwardSettings(),
    top_n: int = 10,
    benchmark_symbol: str = "SPY",
) -> DemandShockBaselineReport:
    if top_n <= 0:
        raise ValueError("top_n must be positive")
    snapshots_by_as_of: dict[object, list[HistoricalFeatureSnapshot]] = defaultdict(list)
    for snapshot in snapshots:
        snapshots_by_as_of[snapshot.as_of].append(snapshot)
    dates = sorted(snapshots_by_as_of)
    folds = build_walk_forward_folds(dates, settings)
    scorer_config = load_screener_config()
    loader = price_loader or fetch_adjusted_close_history
    fold_reports: list[DemandShockFoldReport] = []
    all_records: list[PersistedAnalysis] = []
    next_id = 1

    for fold in folds:
        fold_records: list[PersistedAnalysis] = []
        for as_of in dates:
            if as_of < fold.test_start or as_of > fold.test_end:
                continue
            metrics = [snapshot.to_screener_metrics() for snapshot in snapshots_by_as_of[as_of]]
            filtered, _ = apply_filters(metrics, scorer_config["filters"])
            scored = score_demand_shock_metrics(filtered, scorer_config["demand_shock"], lookback_days=30)
            selected = 0
            for result in scored:
                if result.recommendation != Direction.BUY:
                    continue
                if selected >= top_n:
                    break
                source = next(snapshot for snapshot in snapshots_by_as_of[as_of] if snapshot.symbol == result.symbol)
                fold_records.append(
                    PersistedAnalysis(
                        id=next_id,
                        symbol=result.symbol,
                        generated_at=as_of,
                        horizon="2-4W",
                        direction=_enum_value(result.recommendation),
                        confidence=result.confidence,
                        weighted_score=result.opportunity_score,
                        data_quality_score=result.data_quality_score,
                        entry_assessment=_enum_value(result.entry_assessment) if result.entry_assessment else None,
                        current_price=source.to_screener_metrics().get_float("price"),
                        payload={"score_breakdown": result.score_breakdown},
                    )
                )
                next_id += 1
                selected += 1
        evaluation = evaluate_records(fold_records, price_loader=loader, benchmark_symbol=benchmark_symbol)
        fold_reports.append(DemandShockFoldReport(fold=fold, candidate_count=len(fold_records), evaluation=evaluation))
        all_records.extend(fold_records)

    return DemandShockBaselineReport(
        folds=fold_reports,
        evaluation=evaluate_records(all_records, price_loader=loader, benchmark_symbol=benchmark_symbol),
    )


def _enum_value(value: object) -> str:
    return str(getattr(value, "value", value))
