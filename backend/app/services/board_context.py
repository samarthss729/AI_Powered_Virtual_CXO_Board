"""Request-scoped board context passed from orchestrator to demo reasoning."""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from app.services.data_service import CompanyDataProfile, QuestionAnalysis


@dataclass
class BoardTurnContext:
    """Structured context for one executive turn or synthesis."""

    session_id: int | None = None
    question: str = ""
    role: str = ""
    round_number: int = 1
    company_profile: CompanyDataProfile | None = None
    question_analysis: QuestionAnalysis | None = None
    own_round_one: str | None = None
    peer_round_one: dict[str, str] = field(default_factory=dict)
    discussion: list[dict[str, Any]] = field(default_factory=list)


_board_turn: ContextVar[BoardTurnContext | None] = ContextVar("board_turn", default=None)


def set_board_turn(context: BoardTurnContext) -> None:
    _board_turn.set(context)


def get_board_turn() -> BoardTurnContext | None:
    return _board_turn.get()


def clear_board_turn() -> None:
    _board_turn.set(None)
