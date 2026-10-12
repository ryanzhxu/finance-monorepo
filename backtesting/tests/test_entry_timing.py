from datetime import date, timedelta

import pandas as pd

from backtesting.entry_timing import evaluate_entry_timing


def _history(values: list[tuple[float, float, float]]) -> pd.DataFrame:
    start = date(2025, 1, 2)
    index = pd.DatetimeIndex([pd.Timestamp(start + timedelta(days=offset)) for offset in range(len(values))])
    return pd.DataFrame(
        {
            "Open": [item[0] for item in values],
            "High": [item[1] for item in values],
            "Low": [item[2] for item in values],
            "Close": [item[1] for item in values],
            "Volume": [100.0] * len(values),
        },
        index=index,
    )


def test_entry_timing_evaluates_close_and_pullback_without_using_as_of_day_future_data() -> None:
    history = _history(
        [
            (100, 101, 90),
            (96, 98, 94),
            (97, 101, 96),
            (102, 103, 100),
        ]
    )

    outcomes = evaluate_entry_timing("TEST", date(2025, 1, 2), history, horizon_sessions=2)

    close_now, pullback = outcomes
    assert close_now.status == "completed"
    assert close_now.movement_resolution == "daily_ohlcv"
    assert close_now.entry_price == 101.0
    assert close_now.exit_price == 101.0
    assert close_now.forward_return == round(101 / 101 - 1, 6)
    assert close_now.max_drawdown == round(94 / 101 - 1, 6)
    assert close_now.max_drawdown_date == date(2025, 1, 3)
    assert close_now.max_drawdown_sessions == 1
    assert close_now.peak_return == 0.0
    assert close_now.peak_return_date == date(2025, 1, 4)
    assert close_now.peak_return_sessions == 2
    assert pullback.status == "completed"
    assert pullback.fill_date == date(2025, 1, 3)
    assert pullback.entry_price == 96.0
    assert pullback.exit_price == 103.0
    assert pullback.forward_return == round(103 / 96 - 1, 6)
    assert pullback.max_drawdown == 0.0
    assert pullback.max_drawdown_date == date(2025, 1, 4)
    assert pullback.max_drawdown_sessions == 1
    assert pullback.peak_return == round(103 / 96 - 1, 6)
    assert pullback.peak_return_date == date(2025, 1, 5)
    assert pullback.peak_return_sessions == 2


def test_entry_timing_marks_untriggered_pullback_and_insufficient_history() -> None:
    history = _history([(100, 101, 99), (101, 102, 100), (102, 103, 101)])

    outcomes = evaluate_entry_timing("TEST", date(2025, 1, 2), history, horizon_sessions=3)

    assert outcomes[0].status == "insufficient_forward_history"
    assert outcomes[1].status == "not_triggered"


def test_entry_timing_does_not_treat_limit_fill_day_extrema_as_post_fill_path() -> None:
    history = pd.DataFrame(
        {
            "Open": [100, 98, 100, 105],
            "High": [101, 150, 106, 110],
            "Low": [99, 70, 99, 104],
            "Close": [100, 100, 105, 108],
            "Volume": [100.0] * 4,
        },
        index=pd.date_range("2025-01-02", periods=4, freq="D"),
    )

    _, pullback = evaluate_entry_timing("TEST", date(2025, 1, 2), history, horizon_sessions=2)

    assert pullback.fill_date == date(2025, 1, 3)
    assert pullback.max_drawdown == round(99 / 97 - 1, 6)
    assert pullback.peak_return == round(110 / 97 - 1, 6)
    assert pullback.first_upside_threshold_date is None
    assert pullback.first_downside_threshold_date is None
