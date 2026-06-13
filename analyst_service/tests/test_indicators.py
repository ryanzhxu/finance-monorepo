from __future__ import annotations

import pandas as pd
import pytest

from analyst_service.core.technicals import compute_technicals, rsi


def test_rsi_known_edge_cases_for_directional_prices() -> None:
    close = pd.Series([float(value) for value in range(1, 40)])
    falling = pd.Series([float(value) for value in range(40, 1, -1)])

    rising_result = rsi(close).iloc[-1]
    falling_result = rsi(falling).iloc[-1]

    assert rising_result == pytest.approx(100.0)
    assert falling_result == pytest.approx(0.0)


def test_compute_technicals_returns_core_levels() -> None:
    index = pd.bdate_range("2025-01-01", periods=260)
    close = pd.Series([100 + (idx * 0.1) for idx in range(260)], index=index)
    frame = pd.DataFrame(
        {
            "open": close - 0.2,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": 1_000_000,
        },
        index=index,
    )

    technicals = compute_technicals(frame)

    assert technicals.ma_20 == pytest.approx(124.95)
    assert technicals.ma_50 == pytest.approx(123.45)
    assert technicals.ma_200 == pytest.approx(115.95)
    assert technicals.atr_14 == pytest.approx(2.0)
    assert technicals.bb_mid == pytest.approx(124.95)
    assert technicals.bb_upper == pytest.approx(126.1033)
    assert technicals.bb_lower == pytest.approx(123.7967)
    assert technicals.support_levels
    assert technicals.resistance_levels
