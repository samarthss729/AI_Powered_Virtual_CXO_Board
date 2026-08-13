"""Metric semantics and evidence-aware reasoning tests."""

from __future__ import annotations

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
from app.services.data_service import analyze_question, build_company_profile
from app.services.file_service import parse_and_normalize
from app.services.metric_semantics import compute_business_direction


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_CSV = PROJECT_ROOT / "data" / "sample_company_data.csv"


def test_dso_lower_is_business_improved():
    assert compute_business_direction("dso", "decreasing") == "improved"
    assert compute_business_direction("dso", "increasing") == "deteriorated"


def test_cac_lower_is_business_improved():
    assert compute_business_direction("cac", "decreasing") == "improved"
    assert compute_business_direction("cac", "increasing") == "deteriorated"


def test_revenue_lower_is_business_deteriorated():
    assert compute_business_direction("revenue", "decreasing") == "deteriorated"


def test_dso_profile_sentence():
    csv = b"Metric,Previous,Current\nDays Sales Outstanding,44,38\n"
    normalized = parse_and_normalize("metrics.csv", csv)
    profile = build_company_profile(normalized, filename="metrics.csv")
    dso = profile.get("dso")
    assert dso is not None
    assert dso.business_direction == "improved"
    sentence = dso.business_compare_sentence()
    assert sentence and "improved" in sentence.lower()


def test_cac_profile_sentence():
    csv = b"Metric,Previous,Current\nCAC,110,98\n"
    normalized = parse_and_normalize("metrics.csv", csv)
    profile = build_company_profile(normalized, filename="metrics.csv")
    cac = profile.get("cac")
    assert cac is not None
    assert cac.business_direction == "improved"


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


def test_ebitda_unavailable_on_csv_without_ebitda_column(demo_client):
    csv = b"Metric,Previous,Current\nOperating Margin,0.12,0.14\nCAC,110,98\n"
    session = demo_client.post("/sessions", json={"title": "No EBITDA"}).json()
    upload = demo_client.post(
        f"/sessions/{session['id']}/upload",
        files={"file": ("ops.csv", csv, "text/csv")},
    )
    assert upload.status_code == 200
    response = demo_client.post(
        f"/sessions/{session['id']}/message",
        json={
            "question": "Why has EBITDA changed compared with the previous period, and what should the CFO recommend?"
        },
    )
    assert response.status_code == 200
    cfo = next(
        x for x in response.json()["discussion"] if x["role"] == "CFO" and x["round"] == 1
    )
    lower = cfo["content"].lower()
    assert "does not contain an explicit ebitda" in lower or "cannot" in lower and "ebitda" in lower
    assert "ebitda deteriorated" not in lower
    assert "ebitda improved" not in lower
    assert "ebitda increased" not in lower
    assert "ebitda decreased" not in lower


def test_round_two_no_prompt_fragment_quotes(demo_client):
    response = demo_client.post("/sessions", json={"title": "R2"}).json()
    session_id = response["id"]
    demo_client.post(
        f"/sessions/{session_id}/upload",
        files={"file": ("sample.csv", SAMPLE_CSV.read_bytes(), "text/csv")},
    )
    payload = demo_client.post(
        f"/sessions/{session_id}/message",
        json={
            "question": "Our market share has changed compared with the previous period. Should we increase marketing investment, maintain it, or reduce it?"
        },
    ).json()
    round_two = [x for x in payload["discussion"] if x["round"] == 2]
    combined = " ".join(x["content"] for x in round_two).lower()
    assert "on \"based on the uploaded" not in combined
    assert "discipline on \"on" not in combined
