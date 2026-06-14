from __future__ import annotations

from datetime import datetime, timezone

from shared.enums import Freshness, ScreenType, TrendSource
from shared.models import ScreenRequest, ScreenResponse, ScreenResultItem, TrendingScreenRequest, TrendingScreenResponse

from backtesting.store import append_screen_results, append_trending_results
from screener_service.core.analyst_client import fetch_analysis, fetch_entry
from screener_service.core.buyability import assess_buyability
from screener_service.core.filters import apply_filters
from screener_service.core.fundamentals_bulk import ScreenerMetrics, fetch_metrics
from screener_service.core.regime import current_regime
from screener_service.core.scoring import score_universe
from screener_service.core.settings import load_screener_config
from screener_service.core.trending import build_trending_results
from screener_service.core.universe import resolve_universe


async def run_screen(request: ScreenRequest, screen_type: ScreenType) -> ScreenResponse:
    config = load_screener_config()
    universe = resolve_universe(request.universe, request.tickers)
    notes: list[str] = []
    if not universe.value:
        response = _empty_response(request, screen_type, universe.freshness, notes)
        append_screen_results(response)
        return response
    fetched = fetch_metrics(universe.value)
    metrics_by_symbol = {symbol: item.value for symbol, item in fetched.items() if item.value is not None}
    metrics = list(metrics_by_symbol.values())
    filters = {**config["filters"], **(request.filters_override or {})}
    filtered, rejected = apply_filters(metrics, filters)
    if rejected:
        notes.append(f"Filtered {len(rejected)} symbols before scoring.")
    regime = current_regime()
    results = score_universe(filtered, config["scoring"], screen_type, regime.market_regime, notes)
    trend_map = {}
    if screen_type == ScreenType.OPPORTUNITIES and results:
        trend_request = TrendingScreenRequest(
            universe=request.universe,
            limit=len(results),
            horizon=request.horizon,
            include_analysis=request.include_analysis,
            include_narrative=request.include_narrative,
            tickers=[item.symbol for item in results],
            filters_override=request.filters_override,
            sources=[
                TrendSource.REDDIT,
                TrendSource.STOCKTWITS,
                TrendSource.NEWS,
                TrendSource.YAHOO_TRENDING,
            ],
        )
        _, trend_map, trend_notes = await build_trending_results(
            trend_request,
            {item.symbol: metrics_by_symbol[item.symbol] for item in results if item.symbol in metrics_by_symbol},
            regime.market_regime,
            config["trend_rules"],
        )
        notes.extend(trend_notes)
        _apply_trending_booster(results, trend_map, float(config["trend_rules"]["metrics"]["booster_weight"]))
    results = results[: request.limit]
    if request.include_analysis:
        if screen_type == ScreenType.OPPORTUNITIES and trend_map:
            await _attach_buyability(results, trend_map, request)
        else:
            await _attach_entries(results, request)
    response_quality = round(sum(item.data_quality_score for item in results) / len(results)) if results else 0
    response_freshness = {"universe": universe.freshness.value, "regime": regime.data_freshness.get("price", Freshness.MISSING.value)}
    response = ScreenResponse(
        screen_type=screen_type,
        generated_at=datetime.now(timezone.utc),
        universe=request.universe,
        market_regime=regime.market_regime,
        data_quality_score=response_quality,
        confidence=round(response_quality / 100, 4),
        data_freshness=response_freshness,
        results=results,
        notes=notes,
    )
    append_screen_results(response)
    return response


async def run_trending_screen(request: TrendingScreenRequest) -> TrendingScreenResponse:
    config = load_screener_config()
    universe = resolve_universe(request.universe, request.tickers)
    notes: list[str] = []
    if not universe.value:
        response = TrendingScreenResponse(
            generated_at=datetime.now(timezone.utc),
            universe=request.universe,
            market_regime=current_regime().market_regime,
            data_quality_score=0,
            confidence=0,
            data_freshness={"universe": universe.freshness.value},
            results=[],
            notes=notes,
        )
        append_trending_results(response)
        return response
    fetched = fetch_metrics(universe.value)
    metrics_by_symbol = {symbol: item.value for symbol, item in fetched.items() if item.value is not None}
    regime = current_regime()
    results, _, trend_notes = await build_trending_results(request, metrics_by_symbol, regime.market_regime, config["trend_rules"])
    notes.extend(trend_notes)
    if request.include_analysis:
        await _attach_trending_buyability(results, request)
    response_quality = round(sum(item.data_quality_score for item in results) / len(results)) if results else 0
    response = TrendingScreenResponse(
        generated_at=datetime.now(timezone.utc),
        universe=request.universe,
        market_regime=regime.market_regime,
        data_quality_score=response_quality,
        confidence=round(response_quality / 100, 4),
        data_freshness={"universe": universe.freshness.value, "regime": regime.data_freshness.get("price", Freshness.MISSING.value)},
        results=results[: request.limit],
        notes=notes,
    )
    append_trending_results(response)
    return response


async def _attach_entries(results: list[ScreenResultItem], request: ScreenRequest) -> None:
    for item in results:
        entry = await fetch_entry(item.symbol, request.horizon)
        if entry is None:
            item.confidence = round(item.confidence * 0.9, 4)
            item.risk_flags = sorted(set([*item.risk_flags, "low_data_quality"]))
            item.reason = f"{item.reason} Analyst entry unavailable; using screener-only score."
            item.summary = item.reason
            continue
        item.entry_assessment = entry.entry_assessment
        item.ideal_buy_zone = entry.ideal_buy_zone


async def _attach_buyability(results: list[ScreenResultItem], trend_map: dict[str, object], request: ScreenRequest) -> None:
    for item in results:
        trend_result = trend_map.get(item.symbol)
        if trend_result is None:
            await _attach_entries([item], request)
            continue
        analysis = await fetch_analysis(item.symbol, request.horizon)
        buyability = assess_buyability(item.symbol, trend_result, item, analysis)
        item.entry_assessment = buyability.entry_assessment
        item.ideal_buy_zone = buyability.ideal_buy_zone
        item.confidence = round(min(item.confidence, buyability.confidence), 4)
        item.risk_flags = sorted(set([*item.risk_flags, *buyability.risk_flags]))
        item.reason = f"{item.reason} {buyability.reason}"
        item.summary = item.reason


async def _attach_trending_buyability(results: list[object], request: TrendingScreenRequest) -> None:
    for item in results:
        analysis = await fetch_analysis(item.symbol, request.horizon)
        buyability = assess_buyability(item.symbol, item, None, analysis)
        item.buyability = buyability


def _apply_trending_booster(results: list[ScreenResultItem], trend_map: dict[str, object], booster_weight: float) -> None:
    for item in results:
        trend_result = trend_map.get(item.symbol)
        if trend_result is None:
            item.score_breakdown["trend_booster"] = {"weight": booster_weight, "applied": False}
            continue
        trend_score = float(trend_result.score_breakdown["trend_score"])
        boosted = round((item.opportunity_score * (1 - booster_weight)) + (trend_score * booster_weight), 2)
        item.opportunity_score = boosted
        item.data_freshness = {**item.data_freshness, **trend_result.data_freshness}
        item.data_quality_score = round((item.data_quality_score + trend_result.data_quality_score) / 2)
        item.confidence = round(min(item.confidence, trend_result.confidence), 4)
        item.risk_flags = sorted(set([*item.risk_flags, *trend_result.risk_flags]))
        item.score_breakdown["trend_booster"] = {
            "weight": booster_weight,
            "trend_score": trend_score,
            "trend_quality": trend_result.trend_quality,
            "acceleration": trend_result.acceleration,
            "retail_fomo_risk": trend_result.retail_fomo_risk,
        }
        item.reason = f"{item.reason} Trend booster applied from acceleration and sentiment."
        item.summary = item.reason
    results.sort(key=lambda result: result.opportunity_score, reverse=True)
    for rank, result in enumerate(results, start=1):
        result.rank = rank


def _empty_response(request: ScreenRequest, screen_type: ScreenType, universe_freshness: Freshness, notes: list[str]) -> ScreenResponse:
    return ScreenResponse(
        screen_type=screen_type,
        generated_at=datetime.now(timezone.utc),
        universe=request.universe,
        market_regime=current_regime().market_regime,
        data_quality_score=0,
        confidence=0,
        data_freshness={"universe": universe_freshness.value},
        results=[],
        notes=notes,
    )
