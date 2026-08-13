"""Tests for material contradiction detection in board decision reasoning."""

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
from app.services.contradiction_helpers import (
    detect_cfo_financial_contradictions,
    detect_coo_operational_constraints,
)
from app.services.data_service import analyze_question, build_company_profile
from app.services.demo_responses import _round_one
from app.services.file_service import parse_and_normalize


GROWTH_WITH_EBITDA_DECLINE_CSV = (
    b"Metric,Previous,Current\n"
    b"Revenue,11200000,12500000\n"
    b"Operating Margin,12,14\n"
    b"CAC,142,125\n"
    b"Market Share,14,18\n"
    b"Customer Count,2850,3200\n"
    b"EBITDA,2000000,1700000\n"
    b"Capacity Utilization,84,91\n"
)

GROWTH_QUESTION = (
    "Revenue, market share, and customer count have all increased, while operating margin and CAC "
    "have also improved. Should the company accelerate growth next period, or focus on consolidating "
    "profitability? What should the board decide, and what conditions should determine the decision?"
)

WORKING_CAPITAL_QUESTION = (
    "Is our working-capital efficiency improving or deteriorating compared with the previous period, "
    "and what should the CFO recommend?"
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


def _profile_and_analysis(csv_bytes: bytes, question: str):
    normalized = parse_and_normalize("metrics.csv", csv_bytes)
    profile = build_company_profile(normalized, filename="metrics.csv")
    return profile, analyze_question(profile, question)


def test_cfo_surfaces_ebitda_contradiction_for_growth_question():
    profile, analysis = _profile_and_analysis(GROWTH_WITH_EBITDA_DECLINE_CSV, GROWTH_QUESTION)
    contradictions = detect_cfo_financial_contradictions(profile, analysis, GROWTH_QUESTION)
    assert any(m.key == "ebitda" for m in contradictions)

    cfo_round_one = _round_one("CFO", GROWTH_QUESTION, profile, analysis).lower()
    assert "contradictory financial evidence" in cfo_round_one
    assert "ebitda" in cfo_round_one
    assert "ebitda bridge" in cfo_round_one or "ebitda declined" in cfo_round_one


def test_coo_surfaces_capacity_constraint_for_growth_question():
    profile, analysis = _profile_and_analysis(GROWTH_WITH_EBITDA_DECLINE_CSV, GROWTH_QUESTION)
    constraints = detect_coo_operational_constraints(profile, analysis, GROWTH_QUESTION)
    assert any(m.key == "capacity_utilization" for m in constraints)

    coo_round_one = _round_one("COO", GROWTH_QUESTION, profile, analysis).lower()
    assert "operational constraint evidence" in coo_round_one or "91" in coo_round_one
    assert "capacity" in coo_round_one


def test_unrelated_question_does_not_surface_contradictions():
    wc_csv = (
        b"Metric,Previous,Current\n"
        b"Days Sales Outstanding,44,38\n"
        b"Revenue,11200000,12500000\n"
        b"EBITDA,2000000,1700000\n"
    )
    profile, analysis = _profile_and_analysis(wc_csv, WORKING_CAPITAL_QUESTION)
    assert detect_cfo_financial_contradictions(profile, analysis, WORKING_CAPITAL_QUESTION) == []
    cfo_round_one = _round_one("CFO", WORKING_CAPITAL_QUESTION, profile, analysis).lower()
    assert "contradictory financial evidence" not in cfo_round_one
    assert "ebitda" not in cfo_round_one


def test_missing_ebitda_behavior_unchanged(demo_client):
    client = demo_client
    no_ebitda = (
        b"Metric,Previous,Current\n"
        b"Revenue,10000000,10800000\n"
        b"Operating Margin,12,14\n"
    )
    session_id = client.post("/sessions", json={"title": "No EBITDA"}).json()["id"]
    client.post(
        f"/sessions/{session_id}/upload",
        files={"file": ("no_ebitda.csv", no_ebitda, "text/csv")},
    )
    payload = client.post(
        f"/sessions/{session_id}/message",
        json={"question": "EBITDA has fallen compared with the previous period. What are the likely drivers?"},
    ).json()
    rec = payload["synthesis"]["recommendation"].lower()
    assert any(p in rec for p in ("not contain", "not available", "cannot verify", "does not contain"))
    assert payload["synthesis"]["confidence"] in {"Low", "Medium"}


def test_sequential_questions_no_contradiction_contamination(demo_client):
    client = demo_client
    session_id = client.post("/sessions", json={"title": "Seq"}).json()["id"]
    client.post(
        f"/sessions/{session_id}/upload",
        files={"file": ("growth.csv", GROWTH_WITH_EBITDA_DECLINE_CSV, "text/csv")},
    )
    r1 = client.post(f"/sessions/{session_id}/message", json={"question": GROWTH_QUESTION}).json()
    r2 = client.post(
        f"/sessions/{session_id}/message",
        json={"question": WORKING_CAPITAL_QUESTION},
    ).json()

    rec2 = r2["synthesis"]["recommendation"].lower()
    assert GROWTH_QUESTION[:40].lower() not in rec2
    assert "contradictory financial evidence" not in rec2
    cfo_r2 = next(x for x in r2["discussion"] if x["role"] == "CFO" and x["round"] == 1)
    assert "ebitda" not in cfo_r2["content"].lower()
    assert r1["synthesis"]["recommendation"]


def test_board_recommendation_still_returned_with_contradictions(demo_client):
    client = demo_client
    session_id = client.post("/sessions", json={"title": "Board"}).json()["id"]
    client.post(
        f"/sessions/{session_id}/upload",
        files={"file": ("growth.csv", GROWTH_WITH_EBITDA_DECLINE_CSV, "text/csv")},
    )
    payload = client.post(f"/sessions/{session_id}/message", json={"question": GROWTH_QUESTION}).json()
    synthesis = payload["synthesis"]
    assert synthesis["recommendation"]
    assert synthesis["confidence"]
    assert isinstance(synthesis["disagreements"], list)
    assert isinstance(synthesis["actions"], list)
    assert isinstance(synthesis["metrics"], list)
    rec = synthesis["recommendation"].lower()
    assert "ebitda" in rec
    assert "selective growth" in rec or "decision:" in rec
