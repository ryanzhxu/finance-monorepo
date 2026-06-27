from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from backtesting.store import append_demand_shock_results
from shared.data_quality import compute_data_quality
from shared.enums import Direction, Freshness, ScreenType
from shared.models import ScreenRequest, ScreenResponse, ScreenResultItem

from screener_service.core.analyst_client import fetch_entry
from screener_service.core.filters import apply_filters
from screener_service.core.fundamentals_bulk import ScreenerMetrics, fetch_metrics
from screener_service.core.regime import current_regime
from screener_service.core.settings import load_screener_config
from screener_service.core.universe import resolve_universe


async def run_demand_shock_screen(request: ScreenRequest) -> ScreenResponse:
    config = load_screener_config()
    universe = resolve_universe(request.universe, request.tickers)
    notes: list[str] = []
    if not universe.value:
        response = _empty_response(request, universe.freshness, notes)
        append_demand_shock_results(response)
        return response

    fetched = fetch_metrics(universe.value)
    metrics_by_symbol = {symbol: item.value for symbol, item in fetched.items() if item.value is not None}
    metrics = list(metrics_by_symbol.values())
    filtered, rejected = apply_filters(metrics, config["filters"])
    if rejected:
        notes.append(f"Filtered {len(rejected)} symbols before demand-shock scoring.")

    regime = current_regime()
    results = _score_demand_shock(filtered, config["demand_shock"], request.lookback_days, notes)
    results = results[: request.limit]

    if request.include_analysis:
        await _attach_entries(results, request)

    response_quality = round(sum(item.data_quality_score for item in results) / len(results)) if results else 0
    response = ScreenResponse(
        screen_type=ScreenType.DEMAND_SHOCK,
        generated_at=datetime.now(timezone.utc),
        universe=request.universe,
        market_regime=regime.market_regime,
        data_quality_score=response_quality,
        confidence=round(response_quality / 100, 4),
        data_freshness={"universe": universe.freshness.value, "regime": regime.data_freshness.get("price", Freshness.MISSING.value)},
        results=results,
        notes=notes,
    )
    append_demand_shock_results(response)
    return response


def _score_demand_shock(
    metrics: list[ScreenerMetrics],
    config: dict[str, Any],
    lookback_days: int,
    notes: list[str] | None = None,
) -> list[ScreenResultItem]:
    weights = {key: float(value) for key, value in config["weights"].items()}
    thresholds = config["thresholds"]
    results: list[ScreenResultItem] = []
    for item in metrics:
        revenue_growth = item.get_float("revenue_growth_yoy_pct")
        earnings_growth = item.get_float("earnings_growth_yoy_pct")
        gross_margin = item.get_float("gross_margin_pct")
        operating_margin = item.get_float("operating_margin_pct")
        recommendation_mean = item.get_float("recommendation_mean")
        institutional_pct = item.get_float("institutional_pct")
        insider_pct = item.get_float("insider_pct")
        short_interest = item.get_float("short_percent_float")
        valuation_percentile = item.get_float("self_5y_valuation_percentile")
        market_cap = item.get_float("market_cap")

        revenue_score = _revenue_score(revenue_growth, earnings_growth, thresholds)
        analyst_score = _analyst_score(recommendation_mean)
        margin_score = _margin_score(gross_margin, operating_margin)
        institutional_score = _bounded(institutional_pct, 25, 90)
        insider_score = _inverse_bounded(insider_pct, 0, 12)
        risk_score = _risk_score(short_interest, valuation_percentile, market_cap)
        opportunity_score = _weighted_score(weights, revenue_score, analyst_score, margin_score)

        freshness = item.freshness_map
        quality = compute_data_quality(freshness)
        risk_flags = _risk_flags(item, quality, short_interest, market_cap, risk_score)
        confidence = round((quality / 100) * min(1.0, opportunity_score / 100), 4)
        action = _action(opportunity_score, thresholds)
        reason = _reason(item.symbol, revenue_growth, analyst_score, margin_score, lookback_days, notes)

        results.append(
            ScreenResultItem(
                rank=0,
                symbol=item.symbol,
                screen_type=ScreenType.DEMAND_SHOCK,
                opportunity_score=opportunity_score,
                valuation_score=_inverse_bounded(valuation_percentile, 0, 100),
                growth_score=revenue_score,
                quality_score=margin_score,
                momentum_score=_growth_momentum_score(revenue_growth, earnings_growth),
                analyst_revision_score=analyst_score,
                institutional_accumulation_score=institutional_score,
                insider_activity_score=insider_score,
                risk_score=risk_score,
                score_breakdown={
                    "demand_shock_score": opportunity_score,
                    "revenue_score": revenue_score,
                    "analyst_score": analyst_score,
                    "margin_score": margin_score,
                    "institutional_score": institutional_score,
                    "insider_score": insider_score,
                    "risk_score": risk_score,
                    "revenue_growth_yoy_pct": revenue_growth,
                    "earnings_growth_yoy_pct": earnings_growth,
                    "gross_margin_pct": gross_margin,
                    "operating_margin_pct": operating_margin,
                    "recommendation_mean": recommendation_mean,
                    "short_percent_float": short_interest,
                    "lookback_days": lookback_days,
                },
                data_freshness={key: value.value for key, value in freshness.items()},
                data_quality_score=quality,
                confidence=confidence,
                reason=reason,
                summary=reason,
                recommended_action=action,
                risk_flags=risk_flags,
                recommendation=_direction(opportunity_score, thresholds),
                revenue_accel_pct=_coalesce_percent(revenue_growth, earnings_growth),
                analyst_upgrades_30d=_analyst_upgrade_proxy(recommendation_mean),
                margin_expansion_bps=_margin_expansion_bps(gross_margin, operating_margin),
                components={
                    "revenue_score": revenue_score,
                    "analyst_score": analyst_score,
                    "margin_score": margin_score,
                },
            )
        )

    results.sort(key=lambda result: result.opportunity_score, reverse=True)
    for rank, result in enumerate(results, start=1):
        result.rank = rank
    return results


async def _attach_entries(results: list[ScreenResultItem], request: ScreenRequest) -> None:
    for item in results:
        entry = await fetch_entry(item.symbol, request.horizon)
        if entry is None:
            item.confidence = round(item.confidence * 0.9, 4)
            item.risk_flags = sorted(set([*item.risk_flags, "low_data_quality"]))
            item.reason = f"{item.reason} Analyst entry unavailable; using demand-shock score only."
            item.summary = item.reason
            continue
        item.entry_assessment = entry.entry_assessment
        item.ideal_buy_zone = entry.ideal_buy_zone


def _weighted_score(weights: dict[str, float], revenue_score: float, analyst_score: float, margin_score: float) -> float:
    total = (weights["revenue"] * revenue_score) + (weights["analyst"] * analyst_score) + (weights["margin"] * margin_score)
    return round(max(0.0, min(100.0, total)), 2)


def _revenue_score(revenue_growth: float | None, earnings_growth: float | None, thresholds: dict[str, Any]) -> float:
    revenue = _bounded(revenue_growth, 0, 50)
    earnings = _bounded(earnings_growth, 0, 60)
    if revenue_growth is not None and revenue_growth < float(thresholds["minimum_revenue_growth_pct"]):
        revenue *= 0.5
    return round(_average_available([revenue, earnings]), 2)


def _analyst_score(recommendation_mean: float | None) -> float:
    if recommendation_mean is None:
        return 50.0
    return round(_inverse_bounded(recommendation_mean, 1.0, 5.0), 2)


def _margin_score(gross_margin: float | None, operating_margin: float | None) -> float:
    return round(_average_available([_bounded(gross_margin, 15, 75), _bounded(operating_margin, 0, 35)]), 2)


def _growth_momentum_score(revenue_growth: float | None, earnings_growth: float | None) -> float:
    return round(_average_available([_bounded(revenue_growth, 0, 50), _bounded(earnings_growth, 0, 60)]), 2)


def _risk_score(short_interest: float | None, valuation_percentile: float | None, market_cap: float | None) -> float:
    components = [_bounded(short_interest, 0, 20), _bounded(valuation_percentile, 60, 100), _inverse_bounded(market_cap, 1_000_000_000, 3_000_000_000_000)]
    return round(_average_available(components, missing=50.0), 2)


def _risk_flags(
    item: ScreenerMetrics,
    data_quality_score: int,
    short_interest: float | None,
    market_cap: float | None,
    risk_score: float,
) -> list[str]:
    flags: list[str] = []
    avg_dollar_volume = item.avg_dollar_volume
    price = item.get_float("price")
    if data_quality_score < 50:
        flags.append("low_data_quality")
    if avg_dollar_volume is not None and avg_dollar_volume < 5_000_000:
        flags.append("low_liquidity")
    if price is not None and price < 5:
        flags.append("penny_stock")
    if short_interest is not None and short_interest > 20:
        flags.append("high_short_interest")
    if market_cap is not None and market_cap < 1_000_000_000:
        flags.append("small_cap")
    if risk_score >= 75:
        flags.append("elevated_risk")
    return flags


def _action(score: float, thresholds: dict[str, Any]) -> str:
    if score >= float(thresholds["minimum_score"]):
        return "analyze_deeper"
    if score >= float(thresholds["minimum_score"]) * 0.8:
        return "watch"
    return "skip"


def _direction(score: float, thresholds: dict[str, Any]) -> Direction:
    if score >= float(thresholds["minimum_score"]):
        return Direction.BUY
    if score <= float(thresholds["minimum_score"]) * 0.5:
        return Direction.SELL
    return Direction.HOLD


def _reason(
    symbol: str,
    revenue_growth: float | None,
    analyst_score: float,
    margin_score: float,
    lookback_days: int,
    notes: list[str] | None,
) -> str:
    revenue_text = f"{revenue_growth:.1f}%" if revenue_growth is not None else "n/a"
    note_text = f" {' '.join(notes)}" if notes else ""
    return (
        f"{symbol} shows {revenue_text} revenue growth, analyst score {analyst_score:.1f}, "
        f"and margin score {margin_score:.1f} over the last {lookback_days} days.{note_text}"
    )


def _empty_response(request: ScreenRequest, universe_freshness: Freshness, notes: list[str]) -> ScreenResponse:
    return ScreenResponse(
        screen_type=ScreenType.DEMAND_SHOCK,
        generated_at=datetime.now(timezone.utc),
        universe=request.universe,
        market_regime=current_regime().market_regime,
        data_quality_score=0,
        confidence=0,
        data_freshness={"universe": universe_freshness.value},
        results=[],
        notes=notes,
    )


def _bounded(value: float | None, lower: float, upper: float) -> float:
    if value is None:
        return 50.0
    if upper <= lower:
        return 50.0
    ratio = (value - lower) / (upper - lower)
    return max(0.0, min(100.0, ratio * 100))


def _inverse_bounded(value: float | None, lower: float, upper: float) -> float:
    if value is None:
        return 50.0
    if upper <= lower:
        return 50.0
    ratio = 1 - ((value - lower) / (upper - lower))
    return max(0.0, min(100.0, ratio * 100))


def _average_available(values: list[float | None], missing: float = 50.0) -> float:
    present = [value for value in values if value is not None]
    if not present:
        return missing
    return sum(present) / len(present)


def _coalesce_percent(revenue_growth: float | None, earnings_growth: float | None) -> float | None:
    values = [value for value in [revenue_growth, earnings_growth] if value is not None]
    if not values:
        return None
    return round(max(values), 2)


def _analyst_upgrade_proxy(recommendation_mean: float | None) -> int | None:
    if recommendation_mean is None:
        return None
    proxy = round(max(0.0, (4.5 - recommendation_mean) * 4))
    return int(proxy)


def _margin_expansion_bps(gross_margin: float | None, operating_margin: float | None) -> float | None:
    values = [value for value in [gross_margin, operating_margin] if value is not None]
    if not values:
        return None
    return round((sum(values) / len(values) - 40.0) * 100, 1)
