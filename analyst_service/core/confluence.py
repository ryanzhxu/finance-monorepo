from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from analyst_service.core.fibonacci import FibonacciResult


class _ClassicalEntryLike(Protocol):
    ideal_buy_zone: tuple[float, float]


@dataclass(frozen=True)
class ConfluenceResult:
    classical_zone: tuple[float, float]
    fibonacci_golden_pocket: tuple[float, float]
    overlap: bool
    merged_zone_low: float | None
    merged_zone_high: float | None
    high_conviction: bool
    divergence_note: str | None
    methods_agreeing: list[str]


def compute_confluence(
    classical: _ClassicalEntryLike,
    fibonacci: FibonacciResult,
    current_price: float,
    atr_14: float,
    overlap_tolerance_atr: float = 0.5,
) -> ConfluenceResult:
    del current_price
    classical_zone = (float(classical.ideal_buy_zone[0]), float(classical.ideal_buy_zone[1]))
    fibonacci_zone = (float(fibonacci.golden_pocket_low), float(fibonacci.golden_pocket_high))
    tolerance = float(overlap_tolerance_atr) * float(atr_14)

    low_a, high_a = classical_zone
    low_b, high_b = fibonacci_zone
    intersects = max(low_a, low_b) <= min(high_a, high_b)
    gap = min(abs(low_b - high_a), abs(low_a - high_b))
    overlap = intersects or gap <= tolerance

    if overlap:
        return ConfluenceResult(
            classical_zone=classical_zone,
            fibonacci_golden_pocket=fibonacci_zone,
            overlap=True,
            merged_zone_low=min(low_a, low_b),
            merged_zone_high=max(high_a, high_b),
            high_conviction=True,
            divergence_note=None,
            methods_agreeing=["swing_sr", "fibonacci_golden_pocket"],
        )

    return ConfluenceResult(
        classical_zone=classical_zone,
        fibonacci_golden_pocket=fibonacci_zone,
        overlap=False,
        merged_zone_low=None,
        merged_zone_high=None,
        high_conviction=False,
        divergence_note=(
            f"Classical zone ${low_a:.2f}–${high_a:.2f} and "
            f"Fibonacci golden pocket ${low_b:.2f}–${high_b:.2f} do not overlap."
        ),
        methods_agreeing=[],
    )
