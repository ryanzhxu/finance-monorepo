from __future__ import annotations

from fastapi import APIRouter, HTTPException

from shared.models import AnalyzeRequest, AnalyzeResponse, BatchAnalyzeRequest, EntryBlock, EntryRequest, HealthResponse

from analyst_service.core.analysis import analyze_symbol, entry_for_symbol
from analyst_service.core.llm_client import llm_available
from analyst_service.core.settings import load_service_config

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    config_valid = True
    try:
        load_service_config()
    except Exception:
        config_valid = False
    return HealthResponse(
        status="ok" if config_valid else "degraded",
        service="analyst_service",
        config_valid=config_valid,
        providers={"yfinance": "optional", "alpha_vantage": "not_configured"},
        llm_available=llm_available(),
        cache_backend="file",
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


@router.post("/entry", response_model=EntryBlock)
async def entry(request: EntryRequest) -> EntryBlock:
    try:
        return await entry_for_symbol(request)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
