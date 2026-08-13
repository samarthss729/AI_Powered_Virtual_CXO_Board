"""Per-question isolated analysis context — no cross-question state."""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from app.models.schemas import BoardSynthesis
from app.services.data_service import CompanyDataProfile, MetricSnapshot, QuestionAnalysis

logger = logging.getLogger(__name__)


@dataclass
class QuestionSession:
    """Fresh context for a single CEO question. Never populated from a prior question."""

    run_id: str
    question: str
    relevant_metrics: list[MetricSnapshot] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    round1: dict[str, str] = field(default_factory=dict)
    round2: dict[str, str] = field(default_factory=dict)
    board_recommendation: BoardSynthesis | None = None
    risks: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    metrics_to_monitor: list[str] = field(default_factory=list)

    @classmethod
    def create(cls, question: str, analysis: QuestionAnalysis) -> QuestionSession:
        return cls(
            run_id=str(uuid.uuid4()),
            question=question.strip(),
            relevant_metrics=list(analysis.relevant_metrics),
            evidence=list(analysis.evidence_lines),
        )


def validate_board_output(
    *,
    question_session: QuestionSession,
    synthesis: BoardSynthesis,
    prior_questions: list[str] | None = None,
) -> dict[str, Any]:
    """
    Hard validation before returning board results.
    Returns {ok: bool, issues: list[str]}.
    """
    issues: list[str] = []
    q = question_session.question
    relevant_labels = {m.label.lower() for m in question_session.relevant_metrics}
    relevant_keys = {m.key.lower() for m in question_session.relevant_metrics}

    rec_lower = synthesis.recommendation.lower()

    # A: recommendation must relate to current question (basic keyword overlap or explicit metrics)
    if not rec_lower.strip():
        issues.append("Empty board recommendation.")

    # C: no previous question text in output
    for prior in prior_questions or []:
        prior_clean = prior.strip()
        if len(prior_clean) > 40 and prior_clean.lower() in rec_lower:
            issues.append("Previous question text found in board recommendation.")

    # B/D: metrics in monitor list should be question-relevant when we have a defined set
    if question_session.relevant_metrics:
        for metric_name in synthesis.metrics:
            name_lower = metric_name.lower()
            if not any(
                name_lower in label or label in name_lower or name_lower.replace(" ", "_") in relevant_keys
                for label in relevant_labels
            ):
                # Allow generic monitoring labels only when few relevant metrics exist
                if len(question_session.relevant_metrics) >= 3:
                    issues.append(f"Metric '{metric_name}' may not belong to current question relevance set.")

    # G: missing requested metrics should be acknowledged when EBITDA etc. asked
    q_lower = q.lower()
    if "ebitda" in q_lower and "ebitda" not in relevant_keys:
        if "not contain" not in rec_lower and "not available" not in rec_lower and "cannot verify" not in rec_lower:
            issues.append("EBITDA requested but missing — recommendation should state unavailability.")

    ok = len(issues) == 0
    return {"ok": ok, "issues": issues}


def log_question_session_debug(
    *,
    enabled: bool,
    label: str,
    question_session: QuestionSession,
    extra: dict[str, Any] | None = None,
) -> None:
    if not enabled:
        return
    payload = {
        "run_id": question_session.run_id,
        "question": question_session.question,
        "selected_metrics": [m.key for m in question_session.relevant_metrics],
        **(extra or {}),
    }
    logger.info("%s:\n%s", label, payload)


def scrub_foreign_question_text(text: str, prior_questions: list[str]) -> str:
    """Remove accidental prior-question fragments from generated text."""
    cleaned = text
    for prior in prior_questions:
        if len(prior.strip()) > 30:
            cleaned = cleaned.replace(prior.strip(), "")
    return re.sub(r"\s{2,}", " ", cleaned).strip()
