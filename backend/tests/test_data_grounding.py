"""Data grounding and demo reasoning integration tests."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.models.database import Base, get_db
from app.services.ai_service import AIService
from app.services.board_service import BoardService
from app.services.data_service import analyze_question, build_company_profile
from app.services.file_service import parse_and_normalize


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_CSV = PROJECT_ROOT / "data" / "sample_company_data.csv"
SAMPLE_BYTES = SAMPLE_CSV.read_bytes()


@pytest.fixture()
def demo_client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()

    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db

    with patch.dict(os.environ, {"DEMO_MODE": "true", "OPENAI_API_KEY": ""}, clear=False):
        from app.core.config import get_settings

        get_settings.cache_clear()
        with TestClient(app) as client:
            yield client, db
        get_settings.cache_clear()

    app.dependency_overrides.clear()
    db.close()
    Base.metadata.drop_all(bind=engine)


def _create_session_with_csv(client: TestClient, title: str = "Data Test") -> int:
    session = client.post("/sessions", json={"title": title}).json()
    upload = client.post(
        f"/sessions/{session['id']}/upload",
        files={"file": ("sample_company_data.csv", SAMPLE_BYTES, "text/csv")},
    )
    assert upload.status_code == 200, upload.text
    return session["id"]


def _ask(client: TestClient, session_id: int, question: str) -> dict:
    response = client.post(f"/sessions/{session_id}/message", json={"question": question})
    assert response.status_code == 200, response.text
    return response.json()


def test_sample_csv_columns_detected():
    normalized = parse_and_normalize("sample_company_data.csv", SAMPLE_BYTES)
    assert "Quarter" in normalized["fields"]
    assert "Revenue" in normalized["fields"]
    assert "EBITDA" in normalized["fields"]
    assert "Gross_Margin" in normalized["fields"]
    assert normalized["record_count"] == 3


def test_company_profile_trends_from_sample_csv():
    normalized = parse_and_normalize("sample_company_data.csv", SAMPLE_BYTES)
    profile = build_company_profile(normalized, filename="sample_company_data.csv")
    revenue = profile.get("revenue")
    ebitda = profile.get("ebitda")
    gross = profile.get("gross_margin")
    assert revenue and revenue.current == 10_800_000
    assert revenue.previous == 11_000_000
    assert revenue.trend == "decreasing"
    assert ebitda and ebitda.trend == "decreasing"
    assert gross and gross.current == pytest.approx(36.0)
    assert gross.previous == pytest.approx(40.0)


def test_financial_performance_mixed_assessment():
    normalized = parse_and_normalize("sample_company_data.csv", SAMPLE_BYTES)
    profile = build_company_profile(normalized, filename="sample_company_data.csv")
    analysis = analyze_question(
        profile,
        "Is our overall financial performance improving or deteriorating compared with the previous period?",
    )
    assert profile.has_upload
    assert analysis.evidence_lines
    assert "don't have enough uploaded" not in " ".join(analysis.evidence_lines).lower()


def test_demo_board_uses_uploaded_csv_not_missing_data_message(demo_client):
    client, _db = demo_client
    session_id = _create_session_with_csv(client)
    payload = _ask(
        client,
        session_id,
        "Is our overall financial performance improving or deteriorating compared with the previous period?",
    )
    cfo_r1 = next(item for item in payload["discussion"] if item["role"] == "CFO" and item["round"] == 1)
    text = cfo_r1["content"].lower()
    assert "don't have enough uploaded" not in text
    assert "no company data is uploaded" not in text
    assert any(token in text for token in ("revenue", "ebitda", "margin", "mixed", "decreasing", "increasing"))


def test_ebitda_revenue_question_uses_data(demo_client):
    client, _db = demo_client
    session_id = _create_session_with_csv(client)
    payload = _ask(client, session_id, "Why might EBITDA have decreased even though revenue increased?")
    cfo = next(item for item in payload["discussion"] if item["role"] == "CFO" and item["round"] == 1)
    lower = cfo["content"].lower()
    assert "ebitda" in lower
    assert "revenue" in lower
    assert "don't have enough uploaded" not in lower


def test_market_share_question_distinct_personas(demo_client):
    client, _db = demo_client
    session_id = _create_session_with_csv(client)
    payload = _ask(
        client,
        session_id,
        "Our market share increased from 14% to 18%. Should we increase marketing spend further?",
    )
    round_one = [item for item in payload["discussion"] if item["round"] == 1]
    texts = {item["role"]: item["content"] for item in round_one}
    assert len(set(texts.values())) == 4


def test_round_two_quotes_actual_peer_content(demo_client):
    client, _db = demo_client
    session_id = _create_session_with_csv(client)
    payload = _ask(
        client,
        session_id,
        "Should we reduce operating expenses by 10%?",
    )
    round_one = {item["role"]: item["content"] for item in payload["discussion"] if item["round"] == 1}
    cfo_r2 = next(item for item in payload["discussion"] if item["role"] == "CFO" and item["round"] == 2)
    # Round 2 must not invent CMO marketing reduction if CMO did not propose it
    cmo_r1 = round_one["CMO"].lower()
    if "reduce marketing" not in cmo_r1 and "marketing cut" not in cmo_r1:
        assert "cmo proposed marketing reductions" not in cfo_r2["content"].lower()


def test_session_isolation(demo_client):
    client, db = demo_client
    normalized_a = parse_and_normalize("a.csv", b"Quarter,Revenue\nQ1,100\nQ2,200")
    normalized_b = parse_and_normalize("b.csv", b"Quarter,Revenue\nQ1,500\nQ2,600")

    session_a = client.post("/sessions", json={"title": "A"}).json()["id"]
    session_b = client.post("/sessions", json={"title": "B"}).json()["id"]

    from app.services import session_service

    session_service.save_upload(
        db,
        session_id=session_a,
        filename="a.csv",
        content_type="text/csv",
        raw_text="Quarter,Revenue\nQ1,100\nQ2,200",
        normalized=normalized_a,
    )
    session_service.save_upload(
        db,
        session_id=session_b,
        filename="b.csv",
        content_type="text/csv",
        raw_text="Quarter,Revenue\nQ1,500\nQ2,600",
        normalized=normalized_b,
    )
    db.commit()

    payload_a = _ask(client, session_a, "What is our revenue trend?")
    payload_b = _ask(client, session_b, "What is our revenue trend?")
    cfo_a = next(x for x in payload_a["discussion"] if x["role"] == "CFO" and x["round"] == 1)["content"]
    cfo_b = next(x for x in payload_b["discussion"] if x["role"] == "CFO" and x["round"] == 1)["content"]
    assert "200" in cfo_a or "$200" in cfo_a.upper() or "100" in cfo_a
    assert "600" in cfo_b or "$600" in cfo_b.upper() or "500" in cfo_b
    assert cfo_a != cfo_b


def test_synthesis_does_not_ask_for_upload_when_data_present(demo_client):
    client, _db = demo_client
    session_id = _create_session_with_csv(client)
    payload = _ask(client, session_id, "What are the biggest risks facing the company based on the uploaded data?")
    synthesis = payload["synthesis"]["recommendation"].lower()
    assert "upload csv" not in synthesis
    assert "no company data is uploaded" not in synthesis
