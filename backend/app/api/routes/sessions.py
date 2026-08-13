"""Session management routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.models.database import get_db
from app.models.schemas import MessageOut, SessionCreate, SessionDetail, SessionOut, UploadedDataOut
from app.services import session_service
from app.services.session_service import SessionNotFoundError

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.get("", response_model=list[SessionOut])
def list_sessions(db: Session = Depends(get_db)) -> list[SessionOut]:
    sessions = session_service.list_sessions(db)
    return [SessionOut(**session_service.session_to_summary(s)) for s in sessions]


@router.post("", response_model=SessionOut, status_code=status.HTTP_201_CREATED)
def create_session(payload: SessionCreate, db: Session = Depends(get_db)) -> SessionOut:
    session = session_service.create_session(db, payload.title)
    return SessionOut(
        id=session.id,
        title=session.title,
        created_at=session.created_at,
        updated_at=session.updated_at,
        message_count=0,
        upload_count=0,
    )


@router.get("/{session_id}", response_model=SessionDetail)
def get_session(session_id: int, db: Session = Depends(get_db)) -> SessionDetail:
    try:
        session = session_service.get_session(db, session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return SessionDetail(
        **session_service.session_to_summary(session),
        messages=[MessageOut.model_validate(m) for m in session.messages],
        uploads=[UploadedDataOut(**session_service.upload_to_dict(u)) for u in session.uploads],
    )


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_session(session_id: int, db: Session = Depends(get_db)) -> None:
    try:
        session_service.delete_session(db, session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{session_id}/messages", response_model=list[MessageOut])
def get_messages(session_id: int, db: Session = Depends(get_db)) -> list[MessageOut]:
    try:
        messages = session_service.list_messages(db, session_id)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return [MessageOut.model_validate(m) for m in messages]
