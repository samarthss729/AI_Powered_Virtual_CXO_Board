"""Sequential question isolation — no cross-question metric or text leakage."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.models.database import Base, get_db
from app.services.data_service import analyze_question, build_company_profile
from app.services.file_service import parse_and_normalize


CPT_CSV = (
    b"Metric,Previous,Current\n"
    b"Days Sales Outstanding,44,38\n"
    b"Operating Margin,12,14\n"
    b"Market Share,14,18\n"
    b"CAC,142,125\n"
    b"LTV,650,680\n"
    b"Capacity Utilization,70,76\n"
    b"Revenue,10000000,10800000\n"
    b"Gross Margin,40,42\n"
)

SAMPLE_NO_EBITDA = (
    b"Metric,Previous,Current\n"
    b"Revenue,10000000,10800000\n"
    b"Operating Margin,12,14\n"
    b"Gross Margin,40,36\n"
    b"Marketing Spend,1200000,1600000\n"
)


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
            yield client
        get_settings.cache_clear()

    app.dependency_overrides.clear()
    db.close()
    Base.metadata.drop_all(bind=engine)


def _session_with_csv(client: TestClient, csv_bytes: bytes, name: str = "metrics.csv") -> int:
    session_id = client.post("/sessions", json={"title": "Isolation Test"}).json()["id"]
    upload = client.post(
        f"/sessions/{session_id}/upload",
        files={"file": (name, csv_bytes, "text/csv")},
    )
    assert upload.status_code == 200, upload.text
    return session_id


def _ask(client: TestClient, session_id: int, question: str) -> dict:
    response = client.post(f"/sessions/{session_id}/message", json={"question": question})
    assert response.status_code == 200, response.text
    return response.json()


def test_working_capital_metric_selection():
    normalized = parse_and_normalize("wc.csv", CPT_CSV)
    profile = build_company_profile(normalized, filename="wc.csv")
    analysis = analyze_question(
        profile,
        "Is our working-capital efficiency improving or deteriorating compared with the previous period?",
    )
    keys = {m.key for m in analysis.relevant_metrics}
    assert "dso" in keys or any("dso" in k for k in keys)
    assert "market_share" not in keys
    assert "cac" not in keys
    assert "capacity_utilization" not in keys


def test_sequential_questions_no_cross_contamination(demo_client):
    client = demo_client
    session_id = _session_with_csv(client, CPT_CSV)

    q1 = (
        "Is our working-capital efficiency improving or deteriorating compared with the previous period, "
        "and what should the CFO recommend?"
    )
    q2 = (
        "Market share increased significantly while CAC decreased. Should we increase marketing investment "
        "further, and what risks should the board consider?"
    )
    q3 = (
        "Should we prioritize aggressive growth or profitability improvement in the next period? "
        "Use the uploaded data to explain the trade-offs and give the board a recommendation."
    )
    q4 = (
        "EBITDA has fallen compared with the previous period. What are the likely drivers, "
        "and what should the CFO recommend?"
    )

    r1 = _ask(client, session_id, q1)
    r2 = _ask(client, session_id, q2)
    r3 = _ask(client, session_id, q3)
    r4 = _ask(client, session_id, q4)

    assert r2["question"] == q2
    assert r3["question"] == q3
    assert r4["question"] == q4

    rec2 = r2["synthesis"]["recommendation"].lower()
    rec3 = r3["synthesis"]["recommendation"].lower()
    rec4 = r4["synthesis"]["recommendation"].lower()

    # Test 2 must not contain Test 1 working-capital focus as primary answer
    assert "working-capital efficiency" not in rec2 or "dso" in rec2
    assert q1[:40].lower() not in rec2

    # Test 3 must not contain prior questions
    assert q1[:40].lower() not in rec3
    assert q2[:40].lower() not in rec3

    # Test 4 must not contain prior questions
    assert q1[:40].lower() not in rec4
    assert q2[:40].lower() not in rec4
    assert q3[:40].lower() not in rec4

    # Each recommendation should differ
    assert len({r1["synthesis"]["recommendation"], r2["synthesis"]["recommendation"], r3["synthesis"]["recommendation"]}) >= 2


def test_ebitda_missing_low_confidence(demo_client):
    client = demo_client
    session_id = _session_with_csv(client, SAMPLE_NO_EBITDA, "no_ebitda.csv")
    payload = _ask(
        client,
        session_id,
        "EBITDA has fallen compared with the previous period. What are the likely drivers?",
    )
    rec = payload["synthesis"]["recommendation"].lower()
    assert any(
        phrase in rec
        for phrase in ("not contain", "not available", "cannot verify", "does not contain")
    )
    assert payload["synthesis"]["confidence"] in {"Low", "Medium"}


def test_round2_uses_current_question_only(demo_client):
    client = demo_client
    session_id = _session_with_csv(client, CPT_CSV)
    _ask(
        client,
        session_id,
        "Is our working-capital efficiency improving or deteriorating?",
    )
    payload = _ask(
        client,
        session_id,
        "Should we increase marketing investment further?",
    )
    cfo_r2 = next(x for x in payload["discussion"] if x["role"] == "CFO" and x["round"] == 2)
    lower = cfo_r2["content"].lower()
    assert "working-capital" not in lower
    assert "working capital" not in lower
