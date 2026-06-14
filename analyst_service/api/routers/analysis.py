from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import ConfigDict

from shared.models import AnalyzeRequest, AnalyzeResponse, BatchAnalyzeRequest, EntryBlock, EntryRequest, HealthResponse, FreshnessMap

from analyst_service.core.analysis import analyze_symbol
from analyst_service.core.llm_client import llm_available
from analyst_service.core.settings import load_service_config

router = APIRouter()


class EntryResponse(EntryBlock):
    model_config = ConfigDict(use_enum_values=True)

    data_freshness: FreshnessMap
    data_quality_score: int


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
