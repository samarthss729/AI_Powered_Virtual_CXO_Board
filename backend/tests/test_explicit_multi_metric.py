"""Regression tests for explicit multi-metric question selection."""

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
from app.services.data_service import analyze_question, build_company_profile, select_persona_metric_groups
from app.services.demo_responses import _round_one
from app.services.file_service import parse_and_normalize


MULTI_METRIC_CSV = (
    b"Metric,Previous,Current\n"
    b"Revenue,5400000,6100000\n"
    b"Market Share,14,18\n"
    b"Customer Count,2850,3200\n"
    b"Operating Margin,12,14\n"
    b"CAC,142,125\n"
    b"Days Sales Outstanding,44,38\n"
    b"Capacity Utilization,70,76\n"
    b"LTV,650,680\n"
    b"Gross Margin,40,42\n"
)

TEST_A_QUESTION = (
    "Revenue, market share, and customer count have all increased, while operating margin and CAC "
    "have also improved. Should the company accelerate growth next period, or focus on consolidating "
    "profitability? What should the board decide, and what conditions should determine the decision?"
)

MULTI_METRIC_QUESTION = (
    "Using Revenue, Market Share, Customer Count, Operating Margin, and CAC from the uploaded data, "
    "what is the board's assessment of our growth efficiency?"
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


def _profile_and_analysis(question: str):
    normalized = parse_and_normalize("multi.csv", MULTI_METRIC_CSV)
    profile = build_company_profile(normalized, filename="multi.csv")
    return profile, analyze_question(profile, question)


def test_a_growth_decision_selects_all_explicit_metrics():
    profile, analysis = _profile_and_analysis(TEST_A_QUESTION)
    primary_keys = {m.key for m in analysis.primary_metrics}
    assert primary_keys == {
        "revenue",
        "market_share",
        "customer_count",
        "operating_margin",
        "cac",
    }
    assert "capacity_utilization" not in {m.key for m in analysis.relevant_metrics}

    evidence_blob = " ".join(analysis.evidence_lines).lower()
    for token in (
        "revenue",
        "market share",
        "customer count",
        "operating margin",
        "cost per acquisition",
    ):
        assert token in evidence_blob


def test_a_round_one_covers_multiple_metrics_not_cac_only():
    profile, analysis = _profile_and_analysis(TEST_A_QUESTION)
    all_evidence = " ".join(
        _round_one(role, TEST_A_QUESTION, profile, analysis) for role in ("CFO", "CMO", "COO", "CSO")
    ).lower()

    assert "cost per acquisition improved" not in all_evidence or "revenue" in all_evidence
    assert "revenue" in all_evidence
    assert "market share" in all_evidence
    assert "customer count" in all_evidence
    assert "operating margin" in all_evidence
    assert "cost per acquisition" in all_evidence

    # Capacity only as COO supporting evidence, not replacing primaries globally.
    cfo_primary, cfo_secondary = select_persona_metric_groups(
        profile, "CFO", TEST_A_QUESTION, analysis.primary_metrics, analysis.secondary_metrics, analysis.relevant_metrics
    )
    assert {m.key for m in cfo_primary} <= {"revenue", "operating_margin", "cac", "gross_margin"}
    assert "capacity_utilization" not in {m.key for m in cfo_primary}

    coo_primary, coo_secondary = select_persona_metric_groups(
        profile, "COO", TEST_A_QUESTION, analysis.primary_metrics, analysis.secondary_metrics, analysis.relevant_metrics
    )
    assert "capacity_utilization" in {m.key for m in coo_secondary} or "capacity utilization" in _round_one(
        "COO", TEST_A_QUESTION, profile, analysis
    ).lower()


def test_b_working_capital_isolation():
    profile, analysis = _profile_and_analysis(
        "Is our working-capital efficiency improving or deteriorating compared with the previous period, "
        "and what should the CFO recommend?"
    )
    primary_keys = {m.key for m in analysis.primary_metrics}
    assert "dso" in primary_keys
    assert "market_share" not in primary_keys
    assert "cac" not in primary_keys
    assert "capacity_utilization" not in primary_keys


def test_c_marketing_question_selects_share_and_cac():
    profile, analysis = _profile_and_analysis(
        "Should we increase marketing investment given market share increased and CAC decreased?"
    )
    keys = {m.key for m in analysis.relevant_metrics}
    assert "market_share" in keys
    assert "cac" in keys


def test_d_ebitda_missing_not_claimed(demo_client):
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


def test_board_synthesis_uses_all_explicit_metrics(demo_client):
    client = demo_client
    session_id = client.post("/sessions", json={"title": "Multi Metric"}).json()["id"]
    upload = client.post(
        f"/sessions/{session_id}/upload",
        files={"file": ("multi.csv", MULTI_METRIC_CSV, "text/csv")},
    )
    assert upload.status_code == 200

    payload = client.post(
        f"/sessions/{session_id}/message",
        json={"question": TEST_A_QUESTION},
    ).json()

    monitor = {m.lower() for m in payload["synthesis"]["metrics"]}
    assert any("revenue" in m for m in monitor)
    assert any("market share" in m for m in monitor)
    assert any("customer count" in m for m in monitor)
    assert any("operating margin" in m for m in monitor)
    assert any("cost per acquisition" in m or "cac" in m for m in monitor)

    rec = payload["synthesis"]["recommendation"].lower()
    assert "revenue" in rec
    assert "market share" in rec or "14" in rec
    assert "cost per acquisition" in rec or "142" in rec
    assert "days sales outstanding" not in rec
