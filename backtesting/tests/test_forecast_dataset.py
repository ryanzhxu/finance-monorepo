from datetime import date, datetime, timedelta

import pandas as pd
import pytest

from backtesting.forecast_dataset import build_forecast_observations
from backtesting.historical_dataset import HistoricalFeatureSnapshot, HistoricalMetric
from shared.enums import Freshness


def test_forecast_dataset_uses_only_point_in_time_features_and_forward_prices() -> None:
    as_of = datetime(2024, 1, 1)
    snapshot = HistoricalFeatureSnapshot(
        as_of=as_of,
        symbol="ABC",
        values={
            "signal_score": HistoricalMetric(value=80, available_at=as_of, freshness=Freshness.QUARTERLY),
        },
    )
    dates = pd.date_range(as_of.date(), periods=80, freq="D")
    close = pd.Series([100 + index for index in range(len(dates))], index=dates, dtype=float)
    prices = pd.DataFrame({"Open": close + 1, "Low": close - 2, "Close": close}, index=dates)

    observations, skipped = build_forecast_observations(
        [snapshot],
        price_loader=lambda symbol, start, end: prices,
    )

    assert skipped == {}
    assert len(observations) == 1
    assert observations[0].signal_score == 80
    assert observations[0].forward_return_3m > 0
    assert observations[0].label_version == "next_open_low_v2"
    assert observations[0].entry_date == dates[1].date()
    assert observations[0].exit_date == dates[63].date()
    assert observations[0].entry_price == 102
    assert observations[0].exit_price == 163
    assert observations[0].max_drawdown_3m == pytest.approx(99 / 102 - 1)


def test_forecast_dataset_loads_price_history_once_per_symbol() -> None:
    as_of = datetime(2024, 1, 1)
    snapshots = [
        HistoricalFeatureSnapshot(
            as_of=as_of + timedelta(days=offset),
            symbol="ABC",
            values={"signal_score": HistoricalMetric(value=80, available_at=as_of + timedelta(days=offset), freshness=Freshness.QUARTERLY)},
        )
        for offset in (0, 1)
    ]
    close = pd.Series(range(100, 200), index=pd.date_range(as_of.date(), periods=100, freq="D"), dtype=float)
    prices = pd.DataFrame({"Open": close, "Low": close - 1, "Close": close}, index=close.index)
    calls: list[tuple[str, object, object]] = []

    observations, skipped = build_forecast_observations(
        snapshots,
        price_loader=lambda symbol, start, end: (calls.append((symbol, start, end)) or prices),
    )

    assert len(observations) == 2
    assert skipped == {}
    assert len(calls) == 1


def test_forecast_dataset_rejects_future_feature_before_model_training() -> None:
    as_of = datetime(2024, 1, 1)
    try:
        HistoricalFeatureSnapshot(
            as_of=as_of,
            symbol="ABC",
            values={
                "signal_score": HistoricalMetric(
                    value=80,
                    available_at=as_of + timedelta(days=1),
                    freshness=Freshness.QUARTERLY,
                ),
            },
        )
    except ValueError as exc:
        assert "unavailable at snapshot time" in str(exc)
    else:
        raise AssertionError("future feature should be rejected")


def test_forecast_dataset_uses_next_trading_open_after_a_weekend_and_tracks_intraday_drawdown() -> None:
    as_of = datetime(2024, 1, 5)  # Friday close
    snapshot = HistoricalFeatureSnapshot(
        as_of=as_of,
        symbol="ABC",
        values={"signal_score": HistoricalMetric(value=80, available_at=as_of, freshness=Freshness.LAST_CLOSE)},
    )
    dates = pd.date_range("2024-01-05", periods=70, freq="B")
    close = pd.Series(100.0, index=dates)
    prices = pd.DataFrame({"Open": 100.0, "Low": 99.0, "Close": close}, index=dates)
    prices.loc[pd.Timestamp("2024-01-10"), "Low"] = 70.0

    observations, skipped = build_forecast_observations([snapshot], price_loader=lambda *_args: prices)

    assert skipped == {}
    observation = observations[0]
    assert observation.entry_date == date(2024, 1, 8)
    assert observation.exit_date == dates[63].date()
    assert observation.entry_price == 100.0
    assert observation.max_drawdown_3m == pytest.approx(-0.3)
    assert observation.max_drawdown_date == date(2024, 1, 10)


def test_forecast_dataset_v3_records_threshold_timing_without_inventing_intraday_order() -> None:
    as_of = datetime(2024, 1, 5)
    snapshot = HistoricalFeatureSnapshot(
        as_of=as_of,
        symbol="ABC",
        values={"signal_score": HistoricalMetric(value=80, available_at=as_of, freshness=Freshness.LAST_CLOSE)},
    )
    dates = pd.date_range("2024-01-05", periods=70, freq="B")
    prices = pd.DataFrame({"Open": 100.0, "Low": 99.0, "Close": 100.0, "High": 101.0}, index=dates)
    entry_date = pd.Timestamp("2024-01-08")
    prices.loc[entry_date, ["High", "Low"]] = [125.0, 75.0]

    observations, skipped = build_forecast_observations(
        [snapshot],
        price_loader=lambda *_args: prices,
        include_path_timing=True,
    )

    assert skipped == {}
    observation = observations[0]
    assert observation.label_version == "next_open_ohlc_path_v3"
    assert observation.first_upside_threshold_date == entry_date.date()
    assert observation.first_upside_threshold_sessions == 0
    assert observation.first_downside_threshold_date == entry_date.date()
    assert observation.first_downside_threshold_sessions == 0
    assert observation.path_event_order == "same_session"


def test_forecast_dataset_v3_rejects_prices_without_daily_high() -> None:
    as_of = datetime(2024, 1, 5)
    snapshot = HistoricalFeatureSnapshot(
        as_of=as_of,
        symbol="ABC",
        values={"signal_score": HistoricalMetric(value=80, available_at=as_of, freshness=Freshness.LAST_CLOSE)},
    )
    dates = pd.date_range("2024-01-05", periods=70, freq="B")
    prices = pd.DataFrame({"Open": 100.0, "Low": 99.0, "Close": 100.0}, index=dates)

    observations, skipped = build_forecast_observations(
        [snapshot],
        price_loader=lambda *_args: prices,
        include_path_timing=True,
    )

    assert observations == []
    assert skipped == {"missing_high_for_path_timing": 1}
