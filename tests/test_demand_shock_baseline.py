from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from backtesting.demand_shock_baseline import run_demand_shock_baseline
from backtesting.historical_dataset import HistoricalFeatureSnapshot, HistoricalMetric
from backtesting.walk_forward import WalkForwardSettings
from shared.enums import Freshness


def _snapshot(as_of: datetime, symbol: str, **values: float) -> HistoricalFeatureSnapshot:
    freshness = Freshness.LAST_CLOSE if symbol == "NVDA" else Freshness.QUARTERLY
    return HistoricalFeatureSnapshot(
        as_of=as_of,
        symbol=symbol,
        values={
            key: HistoricalMetric(value=value, available_at=as_of, freshness=freshness)
            for key, value in values.items()
        },
    )


def _snapshots() -> list[HistoricalFeatureSnapshot]:
    snapshots: list[HistoricalFeatureSnapshot] = []
    for as_of in pd.bdate_range("2024-01-02", periods=12, tz="UTC"):
        current = as_of.to_pydatetime()
        snapshots.extend(
            [
                _snapshot(
                    current,
                    "NVDA",
                    price=100,
                    market_cap=2_000_000_000_000,
                    avg_volume=30_000_000,
                    revenue_growth_yoy_pct=35,
                    earnings_growth_yoy_pct=30,
                    gross_margin_pct=70,
                    operating_margin_pct=30,
                    recommendation_mean=1.7,
                    institutional_pct=80,
                    insider_pct=4,
                    short_percent_float=3,
                    self_5y_valuation_percentile=25,
                ),
                _snapshot(
                    current,
                    "KO",
                    price=60,
                    market_cap=250_000_000_000,
                    avg_volume=12_000_000,
                    revenue_growth_yoy_pct=3,
                    earnings_growth_yoy_pct=2,
                    gross_margin_pct=30,
                    operating_margin_pct=8,
                    recommendation_mean=3.5,
                    institutional_pct=70,
                    insider_pct=2,
                    short_percent_float=6,
                    self_5y_valuation_percentile=80,
                ),
            ]
        )
    return snapshots


def _price_loader(symbol, start, end):
    index = pd.bdate_range(start, periods=80)
    if symbol == "SPY":
        return pd.Series([100 + value * 0.1 for value in range(len(index))], index=index)
    if symbol == "NVDA":
        return pd.Series([100 + value for value in range(len(index))], index=index)
    return pd.Series([60 + value * 0.05 for value in range(len(index))], index=index)


def test_baseline_scores_only_test_window_candidates() -> None:
    report = run_demand_shock_baseline(
        _snapshots(),
        price_loader=_price_loader,
        settings=WalkForwardSettings(training_sessions=3, validation_sessions=1, test_sessions=2, step_sessions=2, embargo_sessions=1),
        top_n=1,
    )

    assert len(report.folds) == 3
    assert all(fold.candidate_count == 2 for fold in report.folds)
    assert all(result.symbol == "NVDA" for result in report.evaluation.results)
    assert report.evaluation.by_strategy["analysis"].evaluated_count == 6
