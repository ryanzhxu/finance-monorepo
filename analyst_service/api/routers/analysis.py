from __future__ import annotations

import asyncio
import os
from dataclasses import asdict
from datetime import datetime, timezone

import httpx
import pandas as pd
import yfinance as yf
from yfinance.exceptions import YFRateLimitError

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
from analyst_service.core.provider_clients.stockdata import search_stockdata_symbols, stockdata_api_key
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


def _probe_yfinance_download() -> str:
    frame = yf.download("AAPL", period="1mo", interval="1d", progress=False, auto_adjust=False)
    return "ok" if not frame.empty else "empty"


def _probe_yfinance_info() -> str:
    info = yf.Ticker("AAPL").info or {}
    return "ok" if isinstance(info, dict) and bool(info) else "empty"


def _probe_yfinance_options_chain() -> str:
    expiries = yf.Ticker("AAPL").options
    return "ok" if expiries else "empty"


def _probe_yfinance_upgrades() -> str:
    upgrades = yf.Ticker("AAPL").upgrades_downgrades
    if isinstance(upgrades, pd.DataFrame):
        return "ok" if not upgrades.empty else "empty"
    return "empty"


async def _run_yfinance_probe(probe) -> str:
    loop = asyncio.get_running_loop()
    try:
        return await asyncio.wait_for(loop.run_in_executor(None, probe), timeout=5.0)
    except YFRateLimitError:
        return "rate_limited"
    except Exception:
        return "unavailable"


def _summarize_provider_status(statuses: list[str]) -> str:
    if statuses and all(status == "not_configured" for status in statuses):
        return "not_configured"
    if any(status == "rate_limited" for status in statuses):
        return "rate_limited"
    if any(status == "unavailable" for status in statuses):
        return "degraded"
    if any(status == "empty" for status in statuses):
        return "degraded"
    return "ok"


async def _check_yahoo_search() -> str:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(
                "https://query1.finance.yahoo.com/v1/finance/search",
                params={
                    "q": "AAPL",
                    "quotesCount": 1,
                    "newsCount": 0,
                    "enableFuzzyQuery": False,
                    "quotesQueryId": "tss_match_phrase_query",
                },
                headers={"User-Agent": "Mozilla/5.0"},
            )
            response.raise_for_status()
            payload = response.json()
        quotes = payload.get("quotes", []) if isinstance(payload, dict) else []
        return "ok" if isinstance(quotes, list) and len(quotes) > 0 else "empty"
    except Exception:
        return "unavailable"


async def _check_yfinance_feature_statuses() -> dict[str, str]:
    download_status, info_status, options_status, upgrades_status, search_status = await asyncio.gather(
        _run_yfinance_probe(_probe_yfinance_download),
        _run_yfinance_probe(_probe_yfinance_info),
        _run_yfinance_probe(_probe_yfinance_options_chain),
        _run_yfinance_probe(_probe_yfinance_upgrades),
        _check_yahoo_search(),
    )
    feature_statuses = {
        "yfinance.download_ohlcv": download_status,
        "yfinance.info": info_status,
        "yfinance.options_chain": options_status,
        "yfinance.upgrades_downgrades": upgrades_status,
        "yahoo.search": search_status,
    }
    feature_statuses["yfinance"] = _summarize_provider_status(list(feature_statuses.values()))
    return feature_statuses


async def _check_sec_edgar() -> str:
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get("https://data.sec.gov/api/xbrl/frames/")
        return "reachable" if r.status_code == 200 else "unreachable"
    except Exception:
        return "unreachable"


async def _check_stockdata_quote() -> str:
    api_key = stockdata_api_key()
    if not api_key:
        return "not_configured"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(
                "https://api.stockdata.org/v1/data/quote",
                params={"symbols": "AAPL", "api_token": api_key},
            )
            response.raise_for_status()
            payload = response.json()
        rows = payload.get("data") if isinstance(payload, dict) else None
        return "ok" if isinstance(rows, list) and len(rows) > 0 else "empty"
    except Exception:
        return "unavailable"


async def _check_stockdata_eod() -> str:
    api_key = stockdata_api_key()
    if not api_key:
        return "not_configured"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(
                "https://api.stockdata.org/v1/data/eod",
                params={"symbols": "AAPL", "date_from": "2026-01-01", "date_to": "2026-03-31", "sort": "asc", "api_token": api_key},
            )
            response.raise_for_status()
            payload = response.json()
        rows = payload.get("data") if isinstance(payload, dict) else None
        return "ok" if isinstance(rows, list) and len(rows) > 0 else "empty"
    except Exception:
        return "unavailable"


async def _check_stockdata_search() -> str:
    api_key = stockdata_api_key()
    if not api_key:
        return "not_configured"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(
                "https://api.stockdata.org/v1/entity/search",
                params={"search": "AAPL", "api_token": api_key},
            )
            response.raise_for_status()
            payload = response.json()
        rows = payload.get("data") if isinstance(payload, dict) else None
        return "ok" if isinstance(rows, list) and len(rows) > 0 else "empty"
    except Exception:
        return "unavailable"


@router.get("/search")
async def search_symbols(q: str, limit: int = 6) -> list[dict]:
    if not q or len(q.strip()) < 1:
        return []
    if stockdata_api_key():
        try:
            stockdata_results = search_stockdata_symbols(q, limit=limit)
            if stockdata_results:
                return stockdata_results
        except Exception:
            pass
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                "https://query1.finance.yahoo.com/v1/finance/search",
                params={
                    "q": q.strip(),
                    "quotesCount": limit * 4,
                    "newsCount": 0,
                    "enableFuzzyQuery": False,
                    "quotesQueryId": "tss_match_phrase_query",
                },
                headers={"User-Agent": "Mozilla/5.0"},
            )
            resp.raise_for_status()
            data = resp.json()
            quotes = data.get("quotes", [])
            return [
                {
                    "symbol": quote["symbol"],
                    "name": quote.get("longname") or quote.get("shortname") or "",
                    "exchange": quote.get("exchange") or "",
                    "type": quote.get("quoteType") or "",
                }
                for quote in quotes
                if quote.get("quoteType") == "EQUITY" and quote.get("symbol")
            ][:limit]
    except Exception:
        return []


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

    yahoo_statuses, sec_status, stockdata_quote_status, stockdata_eod_status, stockdata_search_status = await asyncio.gather(
        _check_yfinance_feature_statuses(),
        _check_sec_edgar(),
        _check_stockdata_quote(),
        _check_stockdata_eod(),
        _check_stockdata_search(),
    )
    stockdata_statuses = {
        "stockdata.quote": stockdata_quote_status,
        "stockdata.eod": stockdata_eod_status,
        "stockdata.search": stockdata_search_status,
    }
    stockdata_statuses["stockdata"] = _summarize_provider_status(list(stockdata_statuses.values()))

    providers = {
        **stockdata_statuses,
        "alpha_vantage": alpha_vantage_status,
        **yahoo_statuses,
        "marketaux": "configured" if os.getenv("MARKETAUX_API_KEY") else "not_configured",
        "tiingo": "not_configured",
        "reddit": "configured" if os.getenv("REDDIT_CLIENT_ID") else "no_credentials",
        "stocktwits": "configured" if os.getenv("STOCKTWITS_API_KEY") else "no_credentials",
        "sec_edgar": sec_status,
        "redis": redis_status(),
    }

    return HealthResponse(
        status="ok" if config_valid else "degraded",
        service="analyst_service",
        config_valid=config_valid,
        providers=providers,
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


def _current_price(request_price: float | None, ohlcv: FreshValue[object]) -> float | None:
    if request_price is not None:
        return float(request_price)
    frame = ohlcv.value
    if hasattr(frame, "empty") and not frame.empty and "close" in frame:
        return float(frame["close"].iloc[-1])
    return None


def _entry_confluence_response(symbol: str, lookback_days: int | None = None) -> EntryConfluenceResponse:
    config = load_service_config()
    fib_config = load_fibonacci_config()
    effective_lookback = int(lookback_days or fib_config["default_lookback_days"])

    ohlcv = fetch_ohlcv(symbol, None)
    fundamentals_fresh, sentiment_fresh, macro_fresh = fetch_analysis_context(symbol, ohlcv.value)
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
    current_price = _current_price(None, ohlcv)
    if current_price is None:
        return EntryConfluenceResponse(
            symbol=symbol,
            generated_at=datetime.now(timezone.utc).isoformat(),
            current_price=None,
            classical={},
            fibonacci=None,
            confluence=None,
            data_freshness=freshness,
            data_quality_score=data_quality_score,
        )

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
        regime=macro.market_regime.value if hasattr(macro.market_regime, "value") else macro.market_regime,
    )
    classical = EntryResponse(
        **entry_block.model_dump(),
        data_freshness=freshness,
        data_quality_score=int(data_quality_score),
    )
    fibonacci_model = None
    confluence_model = None
    try:
        fibonacci = compute_fibonacci_levels(symbol, ohlcv.value, effective_lookback)
        atr_14 = float(technicals.atr_14 or max(current_price * 0.02, 0.01))
        confluence = compute_confluence(
            classical=classical,
            fibonacci=fibonacci,
            current_price=current_price,
            atr_14=atr_14,
            overlap_tolerance_atr=float(fib_config["overlap_tolerance_atr"]),
        )
        fibonacci_model = FibonacciLevels(**asdict(fibonacci))
        confluence_model = ConfluenceZone(
            classical_zone=list(confluence.classical_zone),
            fibonacci_golden_pocket=list(confluence.fibonacci_golden_pocket),
            overlap=confluence.overlap,
            merged_zone_low=confluence.merged_zone_low,
            merged_zone_high=confluence.merged_zone_high,
            high_conviction=confluence.high_conviction,
            divergence_note=confluence.divergence_note,
            methods_agreeing=confluence.methods_agreeing,
        )
    except ValueError:
        pass

    return EntryConfluenceResponse(
        symbol=symbol,
        generated_at=datetime.now(timezone.utc).isoformat(),
        current_price=classical.current_price,
        classical=classical.model_dump(mode="json"),
        fibonacci=fibonacci_model,
        confluence=confluence_model,
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
