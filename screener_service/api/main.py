from __future__ import annotations

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from screener_service.api.routers.screen import router
from screener_service.core.settings import load_screener_config

app = FastAPI(title="Screener Service", version="0.1.0")
app.include_router(router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "https://finance-web-ui.onrender.com",
        "https://finance-web-ui-dev.onrender.com",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def validate_config() -> None:
    load_screener_config()
