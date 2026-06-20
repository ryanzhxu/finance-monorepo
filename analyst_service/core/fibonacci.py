from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from shared.config_loader import load_yaml_config

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "fibonacci_config.yaml"


@dataclass(frozen=True)
class FibonacciResult:
    swing_high: float
    swing_low: float
    level_0: float
    level_236: float
    level_382: float
    level_500: float
    level_618: float
    level_650: float
    level_786: float
    level_1000: float
    golden_pocket_low: float
    golden_pocket_high: float
    as_of: str
    lookback_days: int


def load_fibonacci_config() -> dict[str, float]:
    return load_yaml_config(
        CONFIG_PATH,
        {
            "default_lookback_days",
            "golden_pocket_low_ratio",
            "golden_pocket_high_ratio",
            "overlap_tolerance_atr",
        },
    )


def compute_fibonacci_levels(
    symbol: str,
    price_df: pd.DataFrame,
    lookback_days: int = 90,
) -> FibonacciResult:
    del symbol
    if len(price_df) < 20:
        raise ValueError("insufficient price history")

    data = price_df.copy()
    data.columns = [str(column).lower() for column in data.columns]
    window = data.tail(lookback_days)
    if window.empty:
        raise ValueError("insufficient price history")

    high_column = "high" if "high" in window.columns else "close"
    low_column = "low" if "low" in window.columns else "close"
    if high_column not in window.columns or low_column not in window.columns:
        raise ValueError("insufficient price history")

    swing_high = float(window[high_column].max())
    swing_low = float(window[low_column].min())
    diff = swing_high - swing_low
    config = load_fibonacci_config()
    golden_low_ratio = float(config["golden_pocket_low_ratio"])
    golden_high_ratio = float(config["golden_pocket_high_ratio"])

    def level(ratio: float) -> float:
        return round(swing_high - (ratio * diff), 4)

    as_of = pd.Timestamp(window.index[-1]).date().isoformat()
    level_618 = level(golden_low_ratio)
    level_650 = level(golden_high_ratio)
    golden_pocket_low = min(level_618, level_650)
    golden_pocket_high = max(level_618, level_650)
    return FibonacciResult(
        swing_high=round(swing_high, 4),
        swing_low=round(swing_low, 4),
        level_0=round(swing_high, 4),
        level_236=level(0.236),
        level_382=level(0.382),
        level_500=level(0.500),
        level_618=level_618,
        level_650=level_650,
        level_786=level(0.786),
        level_1000=round(swing_low, 4),
        golden_pocket_low=golden_pocket_low,
        golden_pocket_high=golden_pocket_high,
        as_of=as_of,
        lookback_days=int(lookback_days),
    )
