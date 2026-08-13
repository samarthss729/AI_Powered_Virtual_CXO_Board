"""Board discussion routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.models.database import get_db
from app.models.schemas import BoardResponse, CEOMessageRequest
from app.services.ai_service import AIServiceError
from app.services.board_service import BoardService
from app.services.session_service import SessionNotFoundError

router = APIRouter(prefix="/sessions", tags=["board"])


@router.post("/{session_id}/message", response_model=BoardResponse)
def ask_board(
    session_id: int,
    payload: CEOMessageRequest,
    db: Session = Depends(get_db),
) -> BoardResponse:
    service = BoardService()
    try:
        return service.run_discussion(db, session_id, payload.question)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except AIServiceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
