from __future__ import annotations

from fastapi import FastAPI

from screener_service.api.routers.screen import router
from screener_service.core.settings import load_screener_config

app = FastAPI(title="Screener Service", version="0.1.0")
app.include_router(router)


@app.on_event("startup")
async def validate_config() -> None:
    load_screener_config()
