from __future__ import annotations

import pandas as pd
import pytest

from analyst_service.core.fibonacci import compute_fibonacci_levels


def _price_frame(rows: int = 30) -> pd.DataFrame:
    dates = pd.bdate_range(end="2026-06-18", periods=rows)
    return pd.DataFrame(
        {
            "High": [110.0] * (rows - 1) + [120.0],
            "Low": [90.0] + [95.0] * (rows - 1),
            "Close": [100.0] * rows,
        },
        index=dates,
    )


def test_fibonacci_levels_known_values() -> None:
    frame = _price_frame()

    result = compute_fibonacci_levels("NVDA", frame, lookback_days=30)

    assert result.swing_high == 120.0
    assert result.swing_low == 90.0
    assert result.level_236 == 112.92
    assert result.level_382 == 108.54
    assert result.level_500 == 105.0
    assert result.level_618 == 101.46
    assert result.level_650 == 100.5
    assert result.level_786 == 96.42


def test_golden_pocket_is_between_618_and_650() -> None:
    result = compute_fibonacci_levels("NVDA", _price_frame(), lookback_days=30)

    assert result.golden_pocket_low < result.golden_pocket_high
    assert result.golden_pocket_low == min(result.level_618, result.level_650)
    assert result.golden_pocket_high == max(result.level_618, result.level_650)


def test_fibonacci_falls_back_to_close_when_no_high_low() -> None:
    dates = pd.bdate_range(end="2026-06-18", periods=25)
    frame = pd.DataFrame({"Close": [float(value) for value in range(100, 125)]}, index=dates)

    result = compute_fibonacci_levels("NVDA", frame, lookback_days=25)

    assert result.swing_high == 124.0
    assert result.swing_low == 100.0


def test_fibonacci_raises_on_insufficient_data() -> None:
    dates = pd.bdate_range(end="2026-06-18", periods=10)
    frame = pd.DataFrame({"Close": [100.0] * 10}, index=dates)

    with pytest.raises(ValueError, match="insufficient price history"):
        compute_fibonacci_levels("NVDA", frame, lookback_days=10)
