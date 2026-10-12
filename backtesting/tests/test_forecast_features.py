from __future__ import annotations

from datetime import date

import pandas as pd

from backtesting.forecast import ForecastObservation
from backtesting.forecast_features import (
    CONTINUOUS_FEATURE_SCHEMA,
    MarketFeatureProvider,
    attach_continuous_features,
    classify_historical_regime,
)
from screener_service.core.regime import _classify_regime


def _history(start: str, *, periods: int = 340, offset: float = 0) -> pd.DataFrame:
    index = pd.date_range(start, periods=periods, freq="B")
    close = pd.Series(range(periods), index=index, dtype=float).add(100 + offset)
    return pd.DataFrame(
        {
            "open": close - 0.5,
            "high": close + 1,
            "low": close - 1,
            "close": close,
            "volume": pd.Series(range(periods), index=index, dtype=float).add(1_000),
        },
        index=index,
    )


def _market_provider() -> MarketFeatureProvider:
    return MarketFeatureProvider({"SPY": _history("2020-01-01"), "QQQ": _history("2020-01-01", offset=10), "^VIX": _history("2020-01-01", offset=-80)})


def test_continuous_features_do_not_change_when_future_prices_change() -> None:
    history = _history("2020-01-01")
    provider = _market_provider()
    as_of = history.index[300].date()
    observation = ForecastObservation(
        as_of=as_of,
        symbol="AAA",
        signal_score=75,
        forward_return_3m=0.3,
        max_drawdown_3m=-0.1,
        label_version="next_open_low_v2",
    )
    first, first_skipped = attach_continuous_features([observation], history, provider)
    altered = history.copy()
    altered.loc[altered.index > pd.Timestamp(as_of), "close"] *= 0.1
    second, second_skipped = attach_continuous_features([observation], altered, provider)

    assert not first_skipped and not second_skipped
    assert first[0].feature_values == second[0].feature_values
    assert first[0].feature_schema_version == CONTINUOUS_FEATURE_SCHEMA
    assert first[0].market_regime == second[0].market_regime


def test_historical_regime_thresholds_match_live_classifier() -> None:
    for spy_gap, qqq_gap, vix in ((4, 4, 20), (-1, 2, 27), (-4, -4, 20), (1, 1, 20)):
        assert classify_historical_regime(spy_gap, qqq_gap, vix) == _classify_regime(spy_gap, qqq_gap, vix).value


def test_missing_benchmark_history_rejects_feature_snapshot() -> None:
    history = _history("2020-01-01")
    provider = MarketFeatureProvider({"SPY": history, "QQQ": history, "^VIX": pd.DataFrame()})
    observation = ForecastObservation(
        as_of=history.index[300].date(),
        symbol="AAA",
        signal_score=60,
        forward_return_3m=0.1,
        max_drawdown_3m=-0.1,
        label_version="next_open_low_v2",
    )
    featured, skipped = attach_continuous_features([observation], history, provider)

    assert not featured
    assert skipped == {"missing_continuous_features": 1}


def test_market_feature_provider_rejects_non_trading_dates() -> None:
    provider = _market_provider()

    assert provider.feature_values_for(date(2020, 12, 26)) is None


def test_feature_payload_has_one_regime_and_only_finite_values() -> None:
    history = _history("2020-01-01")
    observation = ForecastObservation(
        as_of=history.index[300].date(),
        symbol="AAA",
        signal_score=60,
        forward_return_3m=0.1,
        max_drawdown_3m=-0.1,
        label_version="next_open_low_v2",
    )
    featured, skipped = attach_continuous_features([observation], history, _market_provider())

    assert not skipped
    values = featured[0].feature_values
    assert sum(values[name] for name in ("regime_risk_on", "regime_neutral", "regime_risk_off")) == 1
    assert all(pd.notna(value) for value in values.values())
