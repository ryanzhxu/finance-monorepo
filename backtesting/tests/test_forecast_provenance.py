from datetime import date

from backtesting.forecast_provenance import build_yfinance_price_provenance


def test_auto_adjusted_yfinance_provenance_is_not_point_in_time_certified_for_corporate_actions() -> None:
    provenance = build_yfinance_price_provenance(
        requested_start=date(2020, 1, 1),
        requested_end=date(2020, 12, 31),
        symbols_requested=2,
        symbols_with_observations=2,
        run_id="split-and-dividend-fixture",
        snapshot_step_sessions=63,
    )

    assert provenance.adjustment_mode == "auto_adjusted_current_view"
    assert provenance.corporate_actions_available_as_of is False
    assert provenance.point_in_time_certified is False
    assert provenance.universe_membership_point_in_time is False
    assert provenance.snapshot_step_sessions == 63


def test_provenance_records_continuous_feature_schema_and_benchmarks() -> None:
    provenance = build_yfinance_price_provenance(
        requested_start=date(2020, 1, 1),
        requested_end=date(2020, 12, 31),
        symbols_requested=2,
        symbols_with_observations=2,
        run_id="continuous-feature-fixture",
        feature_schema_version="continuous_regime_v1",
        benchmark_symbols=["SPY", "QQQ", "^VIX"],
    )

    assert provenance.feature_schema_version == "continuous_regime_v1"
    assert provenance.benchmark_symbols == ["SPY", "QQQ", "^VIX"]
    assert provenance.point_in_time_certified is False
