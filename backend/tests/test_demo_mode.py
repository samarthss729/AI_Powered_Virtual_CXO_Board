"""Tests for DEMO_MODE mock LLM responses."""

from __future__ import annotations

import json
import os
from unittest.mock import patch

import pytest

from app.agents.cfo import CFO
from app.services.ai_service import AIService
from app.services.board_context import BoardTurnContext, set_board_turn
from app.services.data_service import analyze_question, build_company_profile
from app.services.file_service import parse_and_normalize
from app.services.demo_responses import mock_chat, mock_chat_json


SAMPLE_CSV = (
    b"Quarter,Revenue,Profit\n"
    b"Q1,1000000,100000\n"
    b"Q2,1100000,121000\n"
)


@pytest.fixture()
def demo_ai():
    with patch.dict(os.environ, {"DEMO_MODE": "true", "OPENAI_API_KEY": ""}, clear=False):
        from app.core.config import get_settings

        get_settings.cache_clear()
        service = AIService()
        yield service
        get_settings.cache_clear()


def _context_for(question: str, role: str = "CFO", round_number: int = 1):
    normalized = parse_and_normalize("financials.csv", SAMPLE_CSV)
    profile = build_company_profile(normalized, filename="financials.csv")
    analysis = analyze_question(profile, question)
    set_board_turn(
        BoardTurnContext(
            session_id=1,
            question=question,
            role=role,
            round_number=round_number,
            company_profile=profile,
            question_analysis=analysis,
        )
    )
    structured = json.dumps({"filename": "financials.csv", "metrics": profile.to_log_dict()["metrics"]})
    company_context = f"Uploaded company data file: financials.csv\nSTRUCTURED_COMPANY_DATA:\n{structured}"
    return profile, analysis, company_context


def test_demo_mode_margin_trend_from_upload(demo_ai):
    question = "Is our profit margin increasing or decreasing?"
    profile, analysis, company_context = _context_for(question)
    prompt = f"""CEO question:
{question}

Company data context:
{company_context}

This is Round 1. Provide your independent analysis and recommendation as the CFO.
"""
    response = demo_ai.chat(system_prompt=CFO.build_system_prompt(), user_prompt=prompt)
    assert "don't have enough uploaded" not in response.lower()
    assert any(token in response.lower() for token in ("increasing", "10", "11", "margin"))


def test_demo_mode_synthesis_schema(demo_ai):
    question = "Is our profit margin increasing or decreasing?"
    profile, analysis, company_context = _context_for(question)
    set_board_turn(
        BoardTurnContext(
            session_id=1,
            question=question,
            role="SYNTHESIS",
            round_number=0,
            company_profile=profile,
            question_analysis=analysis,
            discussion=[{"role": "CFO", "round": 1, "content": "Margin rose."}],
        )
    )
    user_prompt = f"""CEO question:
{question}

Company data context:
{company_context}

Full board discussion:
[CFO | Round 1]
Margin rose.
"""
    data = demo_ai.chat_json(system_prompt="Boardroom Synthesizer", user_prompt=user_prompt)
    assert isinstance(data.get("recommendation"), str)
    assert isinstance(data.get("key_risks"), list)
    assert data.get("confidence") in {"High", "Medium", "Low"}


def test_csr_differs_from_margin(demo_ai):
    normalized = parse_and_normalize("financials.csv", SAMPLE_CSV)
    profile = build_company_profile(normalized, filename="financials.csv")
    for question in (
        "Is our profit margin increasing or decreasing?",
        "Is there any possibility for corporate social responsibility?",
    ):
        analysis = analyze_question(profile, question)
        set_board_turn(
            BoardTurnContext(
                session_id=1,
                question=question,
                role="CFO",
                round_number=1,
                company_profile=profile,
                question_analysis=analysis,
            )
        )
        prompt = f"CEO question:\n{question}\n\nCompany data context:\nUploaded\n\nRound 1 as CFO"
        responses = mock_chat(system_prompt=CFO.build_system_prompt(), user_prompt=prompt)
        if "corporate social responsibility" in question.lower():
            csr_response = responses
        else:
            margin_response = responses
    assert csr_response != margin_response
