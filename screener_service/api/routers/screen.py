from __future__ import annotations

from fastapi import APIRouter

from shared.enums import ScreenType, Universe
from shared.models import RegimeResponse, ScreenRequest, ScreenResponse, TrendingScreenRequest, TrendingScreenResponse

from screener_service.core.regime import current_regime
from screener_service.core.screening import run_screen, run_trending_screen
from screener_service.core.settings import load_screener_config

router = APIRouter(prefix="/screen")


@router.get("/health")
async def health() -> dict[str, object]:
    config_valid = True
    try:
        load_screener_config()
    except Exception:
        config_valid = False
    return {
        "status": "ok" if config_valid else "degraded",
        "service": "screener_service",
        "config_valid": config_valid,
        "providers": {"yfinance": "optional", "analyst_service": "optional"},
        "cache_backend": "file",
    }


@router.get("/regime", response_model=RegimeResponse)
async def regime() -> RegimeResponse:
    return current_regime()


@router.post("/undervalued", response_model=ScreenResponse)
async def undervalued(request: ScreenRequest) -> ScreenResponse:
    return await run_screen(request, ScreenType.UNDERVALUED)


@router.post("/opportunities", response_model=ScreenResponse)
async def opportunities(request: ScreenRequest) -> ScreenResponse:
    return await run_screen(request, ScreenType.OPPORTUNITIES)


@router.post("/trending", response_model=TrendingScreenResponse)
async def trending(request: TrendingScreenRequest) -> TrendingScreenResponse:
    return await run_trending_screen(request)


@router.post("/watchlist", response_model=ScreenResponse)
async def watchlist(request: ScreenRequest) -> ScreenResponse:
    return await run_screen(request.model_copy(update={"universe": Universe.WATCHLIST}), ScreenType.WATCHLIST)


@router.post("/custom", response_model=ScreenResponse)
async def custom(request: ScreenRequest) -> ScreenResponse:
    return await run_screen(request.model_copy(update={"universe": Universe.CUSTOM}), ScreenType.CUSTOM)
