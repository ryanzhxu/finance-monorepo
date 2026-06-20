from __future__ import annotations

from types import SimpleNamespace

from analyst_service.core.confluence import compute_confluence
from analyst_service.core.fibonacci import FibonacciResult


def _fibonacci(low: float, high: float) -> FibonacciResult:
    pocket_low = min(low, high)
    pocket_high = max(low, high)
    return FibonacciResult(
        swing_high=120.0,
        swing_low=90.0,
        level_0=120.0,
        level_236=112.92,
        level_382=108.54,
        level_500=105.0,
        level_618=low,
        level_650=high,
        level_786=96.42,
        level_1000=90.0,
        golden_pocket_low=pocket_low,
        golden_pocket_high=pocket_high,
        as_of="2026-06-18",
        lookback_days=90,
    )


def test_overlap_when_zones_intersect() -> None:
    classical = SimpleNamespace(ideal_buy_zone=(99.0, 104.0))

    result = compute_confluence(classical, _fibonacci(101.0, 103.0), current_price=102.0, atr_14=4.0)

    assert result.overlap is True
    assert result.high_conviction is True


def test_no_overlap_populates_divergence_note() -> None:
    classical = SimpleNamespace(ideal_buy_zone=(99.0, 101.0))

    result = compute_confluence(classical, _fibonacci(108.0, 110.0), current_price=102.0, atr_14=4.0)

    assert result.overlap is False
    assert result.high_conviction is False
    assert result.divergence_note is not None


def test_merged_zone_spans_both_zones() -> None:
    classical = SimpleNamespace(ideal_buy_zone=(99.0, 104.0))

    result = compute_confluence(classical, _fibonacci(101.0, 103.0), current_price=102.0, atr_14=4.0)

    assert result.merged_zone_low <= 99.0
    assert result.merged_zone_low <= 101.0
    assert result.merged_zone_high >= 104.0
    assert result.merged_zone_high >= 103.0


def test_overlap_within_atr_tolerance() -> None:
    classical = SimpleNamespace(ideal_buy_zone=(99.0, 100.0))

    result = compute_confluence(
        classical,
        _fibonacci(100.8, 101.2),
        current_price=100.4,
        atr_14=2.0,
        overlap_tolerance_atr=0.5,
    )

    assert result.overlap is True
