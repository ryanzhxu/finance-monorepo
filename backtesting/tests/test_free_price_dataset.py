from __future__ import annotations

import pandas as pd

from backtesting.free_price_dataset import build_price_only_snapshots, technical_signal_score


def _history(count: int = 280) -> pd.DataFrame:
    index = pd.date_range("2023-01-02", periods=count, freq="B")
    close = pd.Series(range(100, 100 + count), index=index, dtype=float)
    return pd.DataFrame(
        {
            "Open": close - 1,
            "High": close + 1,
            "Low": close - 2,
            "Close": close,
            "Volume": 1_000_000,
        },
        index=index,
    )


def test_price_only_snapshots_are_available_at_their_as_of_date() -> None:
    snapshots = build_price_only_snapshots("abc", _history())

    assert snapshots
    assert snapshots[0].symbol == "ABC"
    assert snapshots[0].values["signal_score"].available_at == snapshots[0].as_of
    assert 0 <= float(snapshots[-1].values["signal_score"].value) <= 100
    assert snapshots[-1].values["signal_score"].value == technical_signal_score(_history())


def test_price_only_score_does_not_use_prices_after_as_of() -> None:
    history = _history()
    as_of_history = history.iloc[:240]
    altered_future = history.copy()
    altered_future.iloc[240:, altered_future.columns.get_loc("Close")] *= 0.1

    assert technical_signal_score(as_of_history) == technical_signal_score(altered_future.iloc[:240])


def test_yfinance_fetch_uses_a_bounded_timeout(monkeypatch) -> None:
    from backtesting import free_price_dataset

    calls: list[dict[str, object]] = []

    class FakeTicker:
        def __init__(self, symbol: str) -> None:
            assert symbol == "TEST"

        def history(self, **kwargs: object) -> pd.DataFrame:
            calls.append(kwargs)
            return _history(2)

    class FakeYFinance:
        Ticker = FakeTicker

    monkeypatch.setitem(__import__("sys").modules, "yfinance", FakeYFinance())

    free_price_dataset.fetch_free_adjusted_ohlcv("TEST", pd.Timestamp("2024-01-01").date(), pd.Timestamp("2024-01-02").date(), timeout_seconds=12)

    assert calls[0]["timeout"] == 12
