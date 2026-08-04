from __future__ import annotations

import math
from datetime import datetime
from typing import Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator

from shared.enums import Freshness, MarketRegime


class RegimeV2Inputs(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    generated_at: datetime
    spy_closes: tuple[float, ...]
    qqq_closes: tuple[float, ...]
    vix: float | None = Field(default=None, ge=0)
    sector_closes: dict[str, tuple[float, ...]] = {}
    treasury_2y: float | None = None
    treasury_10y: float | None = None
    freshness: dict[str, Freshness] = {}

    @field_validator("spy_closes", "qqq_closes")
    @classmethod
    def validate_index_closes(cls, values: tuple[float, ...]) -> tuple[float, ...]:
        if not values or any(not math.isfinite(value) or value <= 0 for value in values):
            raise ValueError("index close history must contain positive finite values")
        return values

    @field_validator("sector_closes")
    @classmethod
    def validate_sector_closes(
        cls, values: dict[str, tuple[float, ...]]
    ) -> dict[str, tuple[float, ...]]:
        for symbol, closes in values.items():
            if not closes or any(not math.isfinite(value) or value <= 0 for value in closes):
                raise ValueError(f"sector close history must contain positive finite values: {symbol}")
        return values


class RegimeV2Policy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    lookback_1m_sessions: int = Field(default=21, ge=1)
    lookback_3m_sessions: int = Field(default=63, ge=1)
    vix_risk_off: float = Field(default=25.0, ge=0)
    vix_risk_on: float = Field(default=22.0, ge=0)
    index_risk_off_pct: float = 0.0
    index_risk_on_pct: float = 3.0


class RegimeV2Result(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    market_regime: MarketRegime
    sector_leaders: tuple[str, ...]
    sector_laggards: tuple[str, ...]
    sector_strength: dict[str, float]
    breadth_pct: float | None
    treasury_10y_minus_2y: float | None
    vix: float | None
    data_freshness: dict[str, Freshness]
    unknowns: tuple[str, ...] = ()
    reason: str


def classify_regime_v2(
    inputs: RegimeV2Inputs,
    *,
    policy: RegimeV2Policy | None = None,
) -> RegimeV2Result:
    thresholds = policy or RegimeV2Policy()
    unknowns: set[str] = set()
    spy_1m = _relative_return(inputs.spy_closes, thresholds.lookback_1m_sessions, "SPY", unknowns)
    spy_3m = _relative_return(inputs.spy_closes, thresholds.lookback_3m_sessions, "SPY", unknowns)
    qqq_1m = _relative_return(inputs.qqq_closes, thresholds.lookback_1m_sessions, "QQQ", unknowns)
    qqq_3m = _relative_return(inputs.qqq_closes, thresholds.lookback_3m_sessions, "QQQ", unknowns)

    sector_strength = {
        symbol: _combined_sector_strength(closes, thresholds, symbol, unknowns)
        for symbol, closes in sorted(inputs.sector_closes.items())
    }
    valid_sector_strength = {symbol: value for symbol, value in sector_strength.items() if math.isfinite(value)}
    ranked = sorted(valid_sector_strength.items(), key=lambda item: (-item[1], item[0]))
    leaders = tuple(symbol for symbol, _ in ranked[:3])
    laggards = tuple(symbol for symbol, _ in reversed(ranked[-3:])) if ranked else ()
    breadth_pct = _breadth(valid_sector_strength)
    treasury_spread = (
        round(inputs.treasury_10y - inputs.treasury_2y, 4)
        if inputs.treasury_10y is not None and inputs.treasury_2y is not None
        else None
    )
    if treasury_spread is None:
        unknowns.add("treasury_curve_unavailable")

    market_regime = _classify_market_regime(spy_1m, spy_3m, qqq_1m, qqq_3m, inputs.vix, thresholds)
    if inputs.vix is None:
        unknowns.add("volatility_unavailable")
    if not valid_sector_strength:
        unknowns.add("sector_history_insufficient")

    reason = _reason(market_regime, spy_1m, qqq_1m, inputs.vix, breadth_pct, unknowns)
    return RegimeV2Result(
        market_regime=market_regime,
        sector_leaders=leaders,
        sector_laggards=laggards,
        sector_strength={symbol: round(value, 4) for symbol, value in ranked},
        breadth_pct=round(breadth_pct, 4) if breadth_pct is not None else None,
        treasury_10y_minus_2y=treasury_spread,
        vix=inputs.vix,
        data_freshness=inputs.freshness,
        unknowns=tuple(sorted(unknowns)),
        reason=reason,
    )


def _relative_return(values: tuple[float, ...], lookback: int, label: str, unknowns: set[str]) -> float:
    if len(values) <= lookback:
        unknowns.add(f"{label.lower()}_history_insufficient")
        return math.nan
    return (values[-1] / values[-1 - lookback] - 1) * 100


def _combined_sector_strength(
    values: tuple[float, ...],
    policy: RegimeV2Policy,
    symbol: str,
    unknowns: set[str],
) -> float:
    one_month = _relative_return(values, policy.lookback_1m_sessions, symbol, unknowns)
    three_month = _relative_return(values, policy.lookback_3m_sessions, symbol, unknowns)
    if math.isnan(one_month) or math.isnan(three_month):
        return math.nan
    return one_month * 0.6 + three_month * 0.4


def _breadth(sector_strength: Mapping[str, float]) -> float | None:
    if not sector_strength:
        return None
    return sum(value > 0 for value in sector_strength.values()) / len(sector_strength) * 100


def _classify_market_regime(
    spy_1m: float,
    spy_3m: float,
    qqq_1m: float,
    qqq_3m: float,
    vix: float | None,
    policy: RegimeV2Policy,
) -> MarketRegime:
    if (
        vix is not None
        and vix >= policy.vix_risk_off
        and (math.isnan(spy_1m) or spy_1m < policy.index_risk_off_pct)
    ):
        return MarketRegime.RISK_OFF
    if (
        all(not math.isnan(value) and value < policy.index_risk_off_pct for value in (spy_1m, spy_3m, qqq_1m, qqq_3m))
    ):
        return MarketRegime.RISK_OFF
    if (
        all(not math.isnan(value) and value > policy.index_risk_on_pct for value in (spy_1m, spy_3m, qqq_1m, qqq_3m))
        and (vix is None or vix < policy.vix_risk_on)
    ):
        return MarketRegime.RISK_ON
    return MarketRegime.NEUTRAL


def _reason(
    regime: MarketRegime,
    spy_1m: float,
    qqq_1m: float,
    vix: float | None,
    breadth_pct: float | None,
    unknowns: set[str],
) -> str:
    if math.isnan(spy_1m) or math.isnan(qqq_1m):
        return "Regime is neutral because index history is insufficient."
    details = [f"SPY 1M {spy_1m:.2f}%", f"QQQ 1M {qqq_1m:.2f}%"]
    if vix is not None:
        details.append(f"VIX {vix:.2f}")
    if breadth_pct is not None:
        details.append(f"sector breadth {breadth_pct:.1f}%")
    if unknowns:
        details.append("unknown inputs surfaced")
    return f"{regime.value}: " + ", ".join(details) + "."
