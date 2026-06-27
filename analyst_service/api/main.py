from __future__ import annotations

from dotenv import load_dotenv

load_dotenv()

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from analyst_service.api.routers.analysis import router
from analyst_service.core.settings import load_service_config

@asynccontextmanager
async def lifespan(app: FastAPI):
    load_service_config()
    yield


app = FastAPI(title="Analyst Service", version="0.1.0", lifespan=lifespan)
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
