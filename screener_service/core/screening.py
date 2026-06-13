from __future__ import annotations

from datetime import datetime, timezone

from shared.enums import Freshness, ScreenType
from shared.models import ScreenRequest, ScreenResponse, ScreenResultItem

from backtesting.store import append_screen_results
from screener_service.core.analyst_client import fetch_entry
from screener_service.core.filters import apply_filters
from screener_service.core.fundamentals_bulk import ScreenerMetrics, fetch_metrics
from screener_service.core.regime import current_regime
from screener_service.core.scoring import score_universe
from screener_service.core.settings import load_screener_config
from screener_service.core.universe import resolve_universe


async def run_screen(request: ScreenRequest, screen_type: ScreenType) -> ScreenResponse:
    config = load_screener_config()
    universe = resolve_universe(request.universe, request.tickers)
    notes: list[str] = []
    if screen_type == ScreenType.OPPORTUNITIES:
        notes.append("Trending booster not applied until Phase 3.")
    if not universe.value:
        response = _empty_response(request, screen_type, universe.freshness, notes)
        append_screen_results(response)
        return response
    fetched = fetch_metrics(universe.value)
    metrics = [item.value for item in fetched.values() if item.value is not None]
    filters = {**config["filters"], **(request.filters_override or {})}
    filtered, rejected = apply_filters(metrics, filters)
    if rejected:
        notes.append(f"Filtered {len(rejected)} symbols before scoring.")
    regime = current_regime()
    results = score_universe(filtered, config["scoring"], screen_type, regime.market_regime, notes)[: request.limit]
    if request.include_analysis:
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
