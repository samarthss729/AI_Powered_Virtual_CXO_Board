"""Board orchestrator: multi-round executive discussion and synthesis."""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy.orm import Session

from app.agents.base_agent import ExecutiveAgent
from app.agents.cfo import CFO
from app.agents.cmo import CMO
from app.agents.coo import COO
from app.agents.cso import CSO
from app.core.config import get_settings
from app.core.prompts import SYNTHESIS_SCHEMA_INSTRUCTIONS, SYNTHESIS_SYSTEM_PROMPT
from app.models.schemas import BoardResponse, BoardSynthesis, DiscussionEntry, MessageOut
from app.services.ai_service import AIService, AIServiceError
from app.services.board_context import BoardTurnContext, clear_board_turn, set_board_turn
from app.services.data_service import (
    analyze_question,
    build_agent_data_summary,
    build_company_profile,
    build_question_scoped_context_block,
)
from app.services.question_session import (
    QuestionSession,
    log_question_session_debug,
    scrub_foreign_question_text,
    validate_board_output,
)
from app.services.synthesis_helpers import compute_synthesis_confidence
from app.services import session_service

logger = logging.getLogger(__name__)

BOARD_AGENTS: list[ExecutiveAgent] = [CFO, CMO, COO, CSO]


class BoardService:
    """Controls discussion rounds, context sharing, and final synthesis."""

    def __init__(self, ai_service: AIService | None = None) -> None:
        self.ai = ai_service or AIService()
        self.settings = get_settings()

    def run_discussion(self, db: Session, session_id: int, question: str) -> BoardResponse:
        session = session_service.get_session(db, session_id)
        cleaned_question = question.strip()
        if not cleaned_question:
            raise ValueError("Question cannot be empty.")

        if not session.messages and (
            session.title.lower().startswith("new ")
            or session.title.lower() in {"untitled board session", "new board session"}
        ):
            session.title = _title_from_question(cleaned_question)
            db.add(session)
            db.commit()

        profile, _full_context = self._load_company_context(db, session_id)
        question_analysis = analyze_question(profile, cleaned_question)
        question_session = QuestionSession.create(cleaned_question, question_analysis)

        # Prior CEO questions are used ONLY for post-generation validation — never in prompts.
        prior_questions = [
            m.content.strip()
            for m in session.messages
            if getattr(m, "role", None) == "CEO" and m.content.strip()
        ]

        company_context = self._build_isolated_company_context(profile, question_analysis)

        log_question_session_debug(
            enabled=getattr(self.settings, "board_debug", False),
            label="QUESTION SESSION START",
            question_session=question_session,
            extra={"session_id": session_id, "prior_question_count": len(prior_questions)},
        )
        self._debug_log("SELECTED METRICS", {
            "run_id": question_session.run_id,
            "question": cleaned_question,
            "primary_metrics": [m.key for m in question_analysis.primary_metrics],
            "secondary_metrics": [m.key for m in question_analysis.secondary_metrics],
            "metrics": [m.key for m in question_analysis.relevant_metrics],
            "missing": question_analysis.missing_metrics,
        })

        session_service.add_message(
            db,
            session_id=session_id,
            speaker="Ananya Kapoor",
            role="CEO",
            content=cleaned_question,
            round_number=None,
        )

        discussion: list[DiscussionEntry] = []
        round_one: dict[str, str] = {}

        for agent in BOARD_AGENTS:
            role_summary = build_agent_data_summary(profile, agent.role, question_analysis)
            self._debug_log(f"DATA PASSED TO {agent.role}", role_summary)

            content = self._run_agent_turn(
                agent=agent,
                session_id=session_id,
                question=cleaned_question,
                company_context=company_context,
                role_data_summary=role_summary,
                round_number=1,
                own_round_one=None,
                peer_opinions=None,
                profile=profile,
                question_analysis=question_analysis,
            )
            round_one[agent.role] = content
            question_session.round1[agent.role] = content
            discussion.append(DiscussionEntry(role=agent.role, round=1, content=content))
            session_service.add_message(
                db,
                session_id=session_id,
                speaker=agent.name,
                role=agent.role,
                content=content,
                round_number=1,
            )

        self._debug_log("ROUND 1 RESPONSES", round_one)

        rounds = max(1, int(self.settings.discussion_rounds))
        if rounds >= 2:
            for agent in BOARD_AGENTS:
                peers = {role: text for role, text in round_one.items() if role != agent.role}
                role_summary = build_agent_data_summary(profile, agent.role, question_analysis)
                self._debug_log(
                    f"ROUND 2 CONTEXT FOR {agent.role}",
                    {
                        "own_round_one": round_one[agent.role][:500],
                        "peers": {role: text[:300] for role, text in peers.items()},
                    },
                )
                content = self._run_agent_turn(
                    agent=agent,
                    session_id=session_id,
                    question=cleaned_question,
                    company_context=company_context,
                    role_data_summary=role_summary,
                    round_number=2,
                    own_round_one=round_one[agent.role],
                    peer_opinions=peers,
                    profile=profile,
                    question_analysis=question_analysis,
                )
                question_session.round2[agent.role] = content
                discussion.append(DiscussionEntry(role=agent.role, round=2, content=content))
                session_service.add_message(
                    db,
                    session_id=session_id,
                    speaker=agent.name,
                    role=agent.role,
                    content=content,
                    round_number=2,
                )

        discussion_payload = [
            {"role": entry.role, "round": entry.round, "content": entry.content}
            for entry in discussion
        ]
        synthesis = self._synthesize(
            session_id=session_id,
            question=cleaned_question,
            company_context=company_context,
            profile=profile,
            question_analysis=question_analysis,
            discussion=discussion,
            discussion_payload=discussion_payload,
        )

        validation = validate_board_output(
            question_session=question_session,
            synthesis=synthesis,
            prior_questions=prior_questions,
        )
        self._debug_log("VALIDATION RESULT", {
            "run_id": question_session.run_id,
            **validation,
        })
        if not validation["ok"]:
            cleaned_rec = scrub_foreign_question_text(synthesis.recommendation, prior_questions)
            synthesis = BoardSynthesis(
                recommendation=cleaned_rec or synthesis.recommendation,
                key_risks=synthesis.key_risks,
                disagreements=synthesis.disagreements,
                actions=synthesis.actions,
                metrics=[
                    m.label
                    for m in question_analysis.relevant_metrics[:6]
                ] or synthesis.metrics,
                confidence=synthesis.confidence,
            )

        question_session.board_recommendation = synthesis
        question_session.risks = synthesis.key_risks
        question_session.actions = synthesis.actions
        question_session.metrics_to_monitor = synthesis.metrics
        synthesis_text = _format_synthesis_message(synthesis)
        session_service.add_message(
            db,
            session_id=session_id,
            speaker="Board",
            role="SYNTHESIS",
            content=synthesis_text,
            round_number=None,
        )

        clear_board_turn()

        messages = [
            MessageOut.model_validate(m)
            for m in session_service.list_messages(db, session_id)
        ]

        return BoardResponse(
            session_id=session_id,
            question=cleaned_question,
            discussion=discussion,
            synthesis=synthesis,
            messages=messages,
        )

    def _load_company_context(self, db: Session, session_id: int) -> tuple[Any, str]:
        upload = session_service.get_latest_upload(db, session_id)
        if not upload:
            profile = build_company_profile(None, filename="")
            return profile, (
                "No company data has been uploaded for this session. "
                "Do not invent internal metrics. Clearly state that recommendations "
                "are based on the information available in the question and discussion."
            )

        try:
            normalized = json.loads(upload.normalized_json)
        except json.JSONDecodeError:
            normalized = {"raw_text": upload.raw_text[:4000]}

        profile = build_company_profile(normalized, filename=upload.filename)
        return profile, ""

    def _build_isolated_company_context(
        self,
        profile: Any,
        question_analysis: Any,
    ) -> str:
        """Prompt context scoped to the current question's relevant metrics only."""
        if not profile.has_upload:
            return (
                "No company data has been uploaded for this session. "
                "Do not invent internal metrics. Clearly state that recommendations "
                "are based on the information available in the question and discussion."
            )
        structured = build_question_scoped_context_block(profile, question_analysis)
        return (
            f"Uploaded company data file: {profile.filename}\n"
            "Analyze ONLY the current CEO question. Use ONLY the metrics listed below.\n"
            "Do not reference prior questions or metrics outside this block.\n"
            f"STRUCTURED_COMPANY_DATA:\n{structured}"
        )

    def _prior_conversation_context(self, messages: list[Any]) -> str:
        """Deprecated: prior conversation must not be injected into agent prompts."""
        return (
            "This analysis is isolated to the current CEO question only. "
            "Do not reference prior board questions or recommendations."
        )

    def _run_agent_turn(
        self,
        *,
        agent: ExecutiveAgent,
        session_id: int,
        question: str,
        company_context: str,
        role_data_summary: str,
        round_number: int,
        own_round_one: str | None,
        peer_opinions: dict[str, str] | None,
        profile: Any,
        question_analysis: Any,
    ) -> str:
        isolation_note = (
            "IMPORTANT: Answer ONLY the current CEO question below. "
            "Do not reference prior questions, prior board recommendations, or unrelated metrics."
        )
        if round_number == 1:
            user_prompt = f"""{isolation_note}

CEO question:
{question}

Company data context (current question metrics only):
{company_context}

Role-specific data summary ({agent.role}):
{role_data_summary}

This is Round 1. Provide your independent analysis and recommendation as the {agent.role}.
Include: conclusion, evidence from company data, persona-specific interpretation, recommendation, and key risks.
Do not summarize the whole board. Speak only for your function.
"""
        else:
            peer_block = "\n\n".join(
                f"{role}:\n{content}" for role, content in (peer_opinions or {}).items()
            )
            user_prompt = f"""{isolation_note}

CEO question:
{question}

Company data context (current question metrics only):
{company_context}

Role-specific data summary ({agent.role}):
{role_data_summary}

This is Round 2. You have now seen your peers' Round 1 opinions for THIS question only:

{peer_block}

Your Round 1 response:
{own_round_one or ""}

Respond as the {agent.role} in natural boardroom dialogue.
- Agree or disagree with specific peer points from Round 1 of THIS question only.
- Do not repeat the same sentence or agreement phrase twice in one response.
- Do not quote long passages or reference prior questions.
- Use uploaded metric facts and business semantics (lower CAC/DSO is generally favorable).
- Never claim a metric changed unless it exists in the uploaded data.
- Add genuinely new reasoning; do not paraphrase your Round 1 answer.
- End with your updated recommendation for the current question.
"""

        set_board_turn(
            BoardTurnContext(
                session_id=session_id,
                question=question,
                role=agent.role,
                round_number=round_number,
                company_profile=profile,
                question_analysis=question_analysis,
                own_round_one=own_round_one,
                peer_round_one=peer_opinions or {},
            )
        )

        try:
            return self.ai.chat(
                system_prompt=agent.build_system_prompt(),
                user_prompt=user_prompt,
                temperature=0.65,
                max_tokens=650,
            )
        finally:
            pass

    def _synthesize(
        self,
        *,
        session_id: int,
        question: str,
        company_context: str,
        profile: Any,
        question_analysis: Any,
        discussion: list[DiscussionEntry],
        discussion_payload: list[dict[str, Any]],
    ) -> BoardSynthesis:
        transcript = "\n\n".join(
            f"[{entry.role} | Round {entry.round}]\n{entry.content}" for entry in discussion
        )
        synthesis_summary = build_agent_data_summary(profile, "SYNTHESIS", question_analysis)
        user_prompt = f"""Analyze ONLY the current CEO question. Do not use prior questions or unrelated metrics.

CEO question:
{question}

Company data context (current question metrics only):
{company_context}

Board data summary:
{synthesis_summary}

Full board discussion for THIS question:
{transcript}

{SYNTHESIS_SCHEMA_INSTRUCTIONS}
"""
        self._debug_log("BOARD SYNTHESIS INPUT", {
            "question": question,
            "has_upload": profile.has_upload,
            "assessment": question_analysis.assessment,
            "discussion_roles": [entry.role for entry in discussion],
        })

        set_board_turn(
            BoardTurnContext(
                session_id=session_id,
                question=question,
                role="SYNTHESIS",
                round_number=0,
                company_profile=profile,
                question_analysis=question_analysis,
                discussion=discussion_payload,
            )
        )

        try:
            data = self.ai.chat_json(
                system_prompt=SYNTHESIS_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                temperature=0.3,
                max_tokens=900,
            )
            return BoardSynthesis(
                recommendation=str(data.get("recommendation") or "No clear recommendation produced."),
                key_risks=_as_str_list(data.get("key_risks")),
                disagreements=_as_str_list(data.get("disagreements")),
                actions=_as_str_list(data.get("actions")),
                metrics=_as_str_list(data.get("metrics")),
                confidence=_normalize_confidence(
                    data.get("confidence"),
                    fallback=compute_synthesis_confidence(question, profile, question_analysis),
                ),
            )
        except AIServiceError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("Synthesis parsing failed")
            raise AIServiceError(f"Failed to build board synthesis: {exc}") from exc

    def _debug_log(self, label: str, payload: Any) -> None:
        if not getattr(self.settings, "board_debug", False):
            return
        logger.info("%s:\n%s", label, json.dumps(payload, indent=2, default=str))


def _as_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _normalize_confidence(value: Any, *, fallback: str = "Medium") -> str:
    text = str(value or fallback).strip().capitalize()
    if text not in {"High", "Medium", "Low"}:
        return fallback if fallback in {"High", "Medium", "Low"} else "Medium"
    return text


def _title_from_question(question: str) -> str:
    cleaned = " ".join(question.strip().split())
    if len(cleaned) <= 60:
        return cleaned.rstrip("?")
    return cleaned[:57].rstrip() + "..."


def _format_synthesis_message(synthesis: BoardSynthesis) -> str:
    risks = "\n".join(f"- {item}" for item in synthesis.key_risks) or "- None noted"
    disagreements = "\n".join(f"- {item}" for item in synthesis.disagreements) or "- Broad alignment"
    actions = "\n".join(f"{i}. {item}" for i, item in enumerate(synthesis.actions, start=1)) or "1. Revisit with more data"
    metrics = "\n".join(f"- {item}" for item in synthesis.metrics) or "- Define KPIs with the board"
    return (
        "BOARD RECOMMENDATION\n\n"
        f"Primary recommendation:\n{synthesis.recommendation}\n\n"
        f"Key risks:\n{risks}\n\n"
        f"Areas of disagreement:\n{disagreements}\n\n"
        f"Recommended actions:\n{actions}\n\n"
        f"Metrics to monitor:\n{metrics}\n\n"
        f"Confidence: {synthesis.confidence}"
    )
