from __future__ import annotations

from datetime import datetime, timezone

from screener_service.core.regime_v2 import RegimeV2Inputs, classify_regime_v2
from shared.enums import Freshness, MarketRegime


def _trend(start: float, daily_change: float, length: int = 70) -> tuple[float, ...]:
    return tuple(start + index * daily_change for index in range(length))


def test_regime_v2_is_deterministic_and_ranks_sector_strength() -> None:
    result = classify_regime_v2(
        RegimeV2Inputs(
            generated_at=datetime(2026, 8, 4, tzinfo=timezone.utc),
            spy_closes=_trend(100, 0.5),
            qqq_closes=_trend(100, 0.7),
            vix=18.0,
            sector_closes={
                "XLK": _trend(100, 0.8),
                "XLE": _trend(100, 0.2),
                "XLF": _trend(100, -0.1),
            },
            treasury_2y=4.0,
            treasury_10y=4.5,
            freshness={"price": Freshness.LAST_CLOSE, "macro": Freshness.DELAYED},
        )
    )

    assert result.market_regime == MarketRegime.RISK_ON
    assert result.sector_leaders == ("XLK", "XLE", "XLF")
    assert result.sector_laggards == ("XLF", "XLE", "XLK")
    assert result.breadth_pct == 66.6667
    assert result.treasury_10y_minus_2y == 0.5
    assert result.unknowns == ()
    assert classify_regime_v2(
        RegimeV2Inputs(
            generated_at=datetime(2026, 8, 4, tzinfo=timezone.utc),
            spy_closes=_trend(100, 0.5),
            qqq_closes=_trend(100, 0.7),
            vix=18.0,
            sector_closes={
                "XLK": _trend(100, 0.8),
                "XLE": _trend(100, 0.2),
                "XLF": _trend(100, -0.1),
            },
            treasury_2y=4.0,
            treasury_10y=4.5,
            freshness={"price": Freshness.LAST_CLOSE, "macro": Freshness.DELAYED},
        )
    ) == result


def test_missing_history_degrades_to_neutral_with_unknowns() -> None:
    result = classify_regime_v2(
        RegimeV2Inputs(
            generated_at=datetime(2026, 8, 4, tzinfo=timezone.utc),
            spy_closes=(100.0, 99.0),
            qqq_closes=(100.0, 99.0),
            sector_closes={"XLK": (100.0, 101.0)},
        )
    )

    assert result.market_regime == MarketRegime.NEUTRAL
    assert "spy_history_insufficient" in result.unknowns
    assert "sector_history_insufficient" in result.unknowns
    assert result.sector_leaders == ()


def test_high_volatility_and_broad_declines_are_risk_off() -> None:
    result = classify_regime_v2(
        RegimeV2Inputs(
            generated_at=datetime(2026, 8, 4, tzinfo=timezone.utc),
            spy_closes=_trend(150, -0.8),
            qqq_closes=_trend(160, -1.0),
            vix=32.0,
            sector_closes={"XLK": _trend(100, -0.5), "XLF": _trend(100, -0.3)},
            treasury_2y=4.5,
            treasury_10y=4.0,
        )
    )

    assert result.market_regime == MarketRegime.RISK_OFF
    assert result.breadth_pct == 0.0
    assert result.treasury_10y_minus_2y == -0.5
