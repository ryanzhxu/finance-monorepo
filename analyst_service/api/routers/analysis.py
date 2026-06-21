from __future__ import annotations

import os
from dataclasses import asdict
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from shared.data_quality import FreshValue, compute_analysis_data_quality, freshness_label
from shared.enums import Freshness
from shared.models import (
    AnalyzeRequest,
    AnalyzeResponse,
    BatchAnalyzeRequest,
    ConfluenceZone,
    EntryBlock,
    EntryConfluenceResponse,
    EntryRequest,
    FibonacciLevels,
    FreshnessMap,
    Fundamentals,
    HealthResponse,
    Macro,
    Sentiment,
)

from analyst_service.core.analysis import analyze_symbol
from analyst_service.core.aggregator import aggregate_recommendation, fetch_analysis_context
from analyst_service.core.confluence import compute_confluence
from analyst_service.core.data_fetcher import fetch_ohlcv
from analyst_service.core.entry_engine import compute_entry
from analyst_service.core.fibonacci import compute_fibonacci_levels, load_fibonacci_config
from analyst_service.core.fundamentals import normalize_fundamentals
from analyst_service.core.cache import backend_name as cache_backend_name, redis_status
from analyst_service.core.llm_client import llm_available
from analyst_service.core.settings import load_service_config
from analyst_service.core.signals import generate_signals
from analyst_service.core.technicals import compute_technicals

router = APIRouter()


class EntryResponse(EntryBlock):
    model_config = ConfigDict(use_enum_values=True)

    data_freshness: FreshnessMap
    data_quality_score: int


class EntryConfluenceRequest(BaseModel):
    symbol: str
    lookback_days: int | None = None


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    config_valid = True
    try:
        load_service_config()
    except Exception:
        config_valid = False
    alpha_vantage_status = (
        "configured"
        if os.getenv("ALPHA_VANTAGE_KEY") or os.getenv("ALPHA_VANTAGE_API_KEY")
        else "not_configured"
    )
    return HealthResponse(
        status="ok" if config_valid else "degraded",
        service="analyst_service",
        config_valid=config_valid,
        providers={
            "yfinance": "optional",
            "alpha_vantage": alpha_vantage_status,
            "redis": redis_status(),
        },
        llm_available=llm_available(),
        cache_backend=cache_backend_name(),
    )


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze(request: AnalyzeRequest) -> AnalyzeResponse:
    try:
        return await analyze_symbol(request)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/batch", response_model=list[AnalyzeResponse])
async def batch_analyze(request: BatchAnalyzeRequest) -> list[AnalyzeResponse]:
    responses: list[AnalyzeResponse] = []
    for symbol in request.symbols:
        responses.append(
            await analyze_symbol(
                AnalyzeRequest(
                    symbol=symbol,
                    asset_type=request.asset_type,
                    horizon=request.horizon,
                    include_narrative=request.include_narrative,
                    include_entry=request.include_entry,
                )
            )
        )
    return responses


@router.post("/entry", response_model=EntryResponse)
async def entry(request: EntryRequest) -> EntryResponse:
    try:
        analysis = await analyze_symbol(
            AnalyzeRequest(
                symbol=request.symbol,
                asset_type=request.asset_type,
                horizon=request.horizon,
                current_price=request.current_price,
                include_narrative=False,
                include_entry=True,
            )
        )
        if analysis.entry is None:
            raise ValueError("entry block was not generated")
        return EntryResponse(
            **analysis.entry.model_dump(),
            data_freshness={"price": analysis.data_freshness.get("price")},
            data_quality_score=analysis.data_quality_score,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _freshness_value(item: FreshValue[object]) -> Freshness | str:
    label = freshness_label(item)
    return item.freshness if label == item.freshness.value else label


def _current_price(request_price: float | None, ohlcv: FreshValue[object]) -> float:
    if request_price is not None:
        return float(request_price)
    frame = ohlcv.value
    if hasattr(frame, "empty") and not frame.empty:
        return float(frame["close"].iloc[-1])
    raise ValueError("current_price is required when market data is unavailable")


def _entry_confluence_response(symbol: str, lookback_days: int | None = None) -> EntryConfluenceResponse:
    config = load_service_config()
    fib_config = load_fibonacci_config()
    effective_lookback = int(lookback_days or fib_config["default_lookback_days"])

    ohlcv = fetch_ohlcv(symbol, None)
    fundamentals_fresh, sentiment_fresh, macro_fresh = fetch_analysis_context(symbol, ohlcv.value)
    current_price = _current_price(None, ohlcv)
    technicals = compute_technicals(ohlcv.value, support_window=int(config["entry_rules"]["support_window"]))
    fundamentals = normalize_fundamentals(fundamentals_fresh.value)
    sentiment = sentiment_fresh.value or Sentiment()
    macro = macro_fresh.value or Macro()

    freshness = {
        "price": _freshness_value(ohlcv),
        "technicals": _freshness_value(ohlcv),
        "fundamentals": _freshness_value(fundamentals_fresh),
        "ratings": _freshness_value(fundamentals_fresh),
        "flows": _freshness_value(sentiment_fresh) if sentiment.institutional_net_shares_last_13f is not None else Freshness.MISSING,
        "sentiment": _freshness_value(sentiment_fresh),
        "macro": _freshness_value(macro_fresh),
    }
    data_quality_score = float(compute_analysis_data_quality(technicals, fundamentals, sentiment, macro))
    signals = generate_signals(technicals, fundamentals, sentiment, macro, config["weights"], config["thresholds"])
    provisional = aggregate_recommendation(
        signals,
        request_horizon := AnalyzeRequest(symbol=symbol).horizon,
        config["thresholds"],
        int(data_quality_score),
        None,
        freshness,
        macro=macro,
        apply_overrides=False,
    )
    entry_block = compute_entry(
        current_price=current_price,
        technicals=technicals,
        fundamentals=fundamentals,
        direction=provisional.direction,
        horizon=request_horizon,
        rules=config["entry_rules"],
        risk_flags=provisional.risk_flags,
    )
    classical = EntryResponse(
        **entry_block.model_dump(),
        data_freshness=freshness,
        data_quality_score=int(data_quality_score),
    )
    fibonacci = compute_fibonacci_levels(symbol, ohlcv.value, effective_lookback)
    atr_14 = float(technicals.atr_14 or max(current_price * 0.02, 0.01))
    confluence = compute_confluence(
        classical=classical,
        fibonacci=fibonacci,
        current_price=current_price,
        atr_14=atr_14,
        overlap_tolerance_atr=float(fib_config["overlap_tolerance_atr"]),
    )
    return EntryConfluenceResponse(
        symbol=symbol,
        generated_at=datetime.now(timezone.utc).isoformat(),
        current_price=classical.current_price,
        classical=classical.model_dump(mode="json"),
        fibonacci=FibonacciLevels(**asdict(fibonacci)),
        confluence=ConfluenceZone(
            classical_zone=list(confluence.classical_zone),
            fibonacci_golden_pocket=list(confluence.fibonacci_golden_pocket),
            overlap=confluence.overlap,
            merged_zone_low=confluence.merged_zone_low,
            merged_zone_high=confluence.merged_zone_high,
            high_conviction=confluence.high_conviction,
            divergence_note=confluence.divergence_note,
            methods_agreeing=confluence.methods_agreeing,
        ),
        data_freshness=freshness,
        data_quality_score=data_quality_score,
    )


@router.post("/entry/confluence", response_model=EntryConfluenceResponse)
async def entry_confluence(request: EntryConfluenceRequest) -> EntryConfluenceResponse:
    try:
        return _entry_confluence_response(request.symbol.strip().upper(), request.lookback_days)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/entry/confluence/{symbol}", response_model=EntryConfluenceResponse)
async def entry_confluence_by_symbol(symbol: str, lookback_days: int | None = None) -> EntryConfluenceResponse:
    return await entry_confluence(EntryConfluenceRequest(symbol=symbol, lookback_days=lookback_days))
