from __future__ import annotations

from dotenv import load_dotenv

load_dotenv()

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from screener_service.api.routers.screen import router
from screener_service.api.routers.shared_spaces import router as shared_spaces_router
from screener_service.core.shared_spaces import SharedSpaceSettings, SharedSpaceStore
from screener_service.core.settings import load_screener_config

@asynccontextmanager
async def lifespan(app: FastAPI):
    load_screener_config()
    settings = SharedSpaceSettings.from_env()
    if settings is not None:
        store = SharedSpaceStore(settings)
        store.initialize()
        app.state.shared_space_store = store
    elif hasattr(app.state, "shared_space_store"):
        delattr(app.state, "shared_space_store")
    yield


app = FastAPI(title="Screener Service", version="0.1.0", lifespan=lifespan)
app.include_router(router)
app.include_router(shared_spaces_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "https://finance-web-ui.onrender.com",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
