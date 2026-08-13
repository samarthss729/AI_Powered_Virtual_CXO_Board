"""Pytest fixtures for API tests with an isolated SQLite database."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.models.database import Base, get_db
from app.services.ai_service import AIService
from app.services.board_service import BoardService


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def client(db_session, monkeypatch):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db

    class FakeAI(AIService):
        def __init__(self) -> None:  # noqa: D107
            pass

        def chat(self, *, system_prompt: str, user_prompt: str, temperature: float = 0.6, max_tokens: int = 700) -> str:
            role = "Executive"
            for candidate in ("CFO", "CMO", "COO", "CSO"):
                if f"as the {candidate}" in user_prompt or f"Respond as the {candidate}" in user_prompt:
                    role = candidate
                    break
            if "Round 2" in user_prompt or "Round 2." in user_prompt:
                return (
                    f"{role} Round 2: I reviewed peer opinions. "
                    "I push back where ROI is unclear, but accept operational investigation as valid."
                )
            return (
                f"{role} Round 1: Based on available information, my priority lens suggests a focused response. "
                "If company data is present I would cite it; otherwise I avoid inventing numbers."
            )

        def chat_json(self, *, system_prompt: str, user_prompt: str, temperature: float = 0.3, max_tokens: int = 900):
            return {
                "recommendation": "Investigate cost-to-serve and cut only low-ROI spend.",
                "key_risks": ["Cutting growth too aggressively", "Missing operational root cause"],
                "disagreements": ["CFO favors broader opex cuts; CMO resists marketing reductions"],
                "actions": ["Audit fulfillment costs", "Pause low-ROI channels", "Revisit pricing"],
                "metrics": ["Gross margin", "CAC", "EBITDA"],
                "confidence": "Medium",
            }

    monkeypatch.setattr("app.api.routes.board.BoardService", lambda: BoardService(ai_service=FakeAI()))

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()
