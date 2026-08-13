"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BACKEND_DIR / ".env")


def _parse_bool(value: str | None, *, default: bool = False) -> bool:
    """Parse common truthy/falsey environment strings."""
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class Settings:
    """Runtime settings for the Boardroom API."""

    def __init__(self) -> None:
        # When DEMO_MODE=true the app runs without OpenAI; no API key is required.
        self.demo_mode: bool = _parse_bool(os.getenv("DEMO_MODE"), default=False)
        self.openai_api_key: str = os.getenv("OPENAI_API_KEY", "").strip()
        self.openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"
        default_db = f"sqlite:///{BACKEND_DIR / 'boardroom.db'}"
        self.database_url: str = os.getenv("DATABASE_URL", default_db).strip() or default_db
        self.cors_origins: str = os.getenv(
            "CORS_ORIGINS",
            "http://localhost:3000,http://127.0.0.1:3000",
        )
        self.max_upload_bytes: int = int(os.getenv("MAX_UPLOAD_BYTES", str(2 * 1024 * 1024)))
        self.discussion_rounds: int = int(os.getenv("DISCUSSION_ROUNDS", "2"))
        self.board_debug: bool = _parse_bool(os.getenv("BOARD_DEBUG"), default=False)

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    def require_openai_key(self) -> str:
        if self.demo_mode:
            raise ValueError(
                "OpenAI is disabled while DEMO_MODE=true. Set DEMO_MODE=false to use live LLM calls."
            )
        key = self.openai_api_key
        if not key or key == "your_key_here":
            raise ValueError(
                "OPENAI_API_KEY is missing. Add it to backend/.env before asking the board."
            )
        return key


@lru_cache
def get_settings() -> Settings:
    return Settings()
