"""FastAPI entrypoint for AI Boardroom."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import board, sessions, uploads
from app.core.config import get_settings
from app.models.database import init_db
from app.models.schemas import HealthResponse

settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="AI Boardroom",
    description="Virtual C-suite boardroom for CEO decision support.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(sessions.router)
app.include_router(board.router)
app.include_router(uploads.router)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    if settings.demo_mode:
        return HealthResponse(
            status="ok",
            openai_configured=True,
            model=settings.openai_model,
            llm_mode="demo",
        )

    configured = bool(settings.openai_api_key) and settings.openai_api_key != "your_key_here"
    return HealthResponse(
        status="ok",
        openai_configured=configured,
        model=settings.openai_model,
        llm_mode="openai",
    )


@app.get("/")
def root() -> dict[str, str]:
    return {
        "message": "AI Boardroom API is running",
        "docs": "/docs",
        "health": "/health",
    }
