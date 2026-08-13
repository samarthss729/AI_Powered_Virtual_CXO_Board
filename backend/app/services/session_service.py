"""CRUD helpers for boardroom sessions, messages, and uploads."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.db_models import MessageModel, SessionModel, UploadedDataModel
from app.services.file_service import preview_text


class SessionNotFoundError(Exception):
    pass


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def create_session(db: Session, title: str) -> SessionModel:
    session = SessionModel(title=title.strip() or "Untitled Board Session")
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def list_sessions(db: Session) -> list[SessionModel]:
    stmt = (
        select(SessionModel)
        .options(selectinload(SessionModel.messages), selectinload(SessionModel.uploads))
        .order_by(SessionModel.updated_at.desc())
    )
    return list(db.scalars(stmt).all())


def get_session(db: Session, session_id: int, *, with_relations: bool = True) -> SessionModel:
    stmt = select(SessionModel).where(SessionModel.id == session_id)
    if with_relations:
        stmt = stmt.options(
            selectinload(SessionModel.messages),
            selectinload(SessionModel.uploads),
        )
    session = db.scalars(stmt).first()
    if not session:
        raise SessionNotFoundError(f"Session {session_id} not found.")
    return session


def delete_session(db: Session, session_id: int) -> None:
    session = get_session(db, session_id, with_relations=False)
    db.delete(session)
    db.commit()


def touch_session(db: Session, session: SessionModel) -> None:
    session.updated_at = utcnow()
    db.add(session)
    db.commit()
    db.refresh(session)


def add_message(
    db: Session,
    *,
    session_id: int,
    speaker: str,
    role: str,
    content: str,
    round_number: int | None = None,
) -> MessageModel:
    message = MessageModel(
        session_id=session_id,
        speaker=speaker,
        role=role,
        content=content,
        round=round_number,
    )
    db.add(message)
    session = get_session(db, session_id, with_relations=False)
    session.updated_at = utcnow()
    db.commit()
    db.refresh(message)
    return message


def list_messages(db: Session, session_id: int) -> list[MessageModel]:
    get_session(db, session_id, with_relations=False)
    stmt = (
        select(MessageModel)
        .where(MessageModel.session_id == session_id)
        .order_by(MessageModel.created_at.asc(), MessageModel.id.asc())
    )
    return list(db.scalars(stmt).all())


def save_upload(
    db: Session,
    *,
    session_id: int,
    filename: str,
    content_type: str,
    raw_text: str,
    normalized: dict,
) -> UploadedDataModel:
    get_session(db, session_id, with_relations=False)
    upload = UploadedDataModel(
        session_id=session_id,
        filename=filename,
        content_type=content_type,
        raw_text=raw_text,
        normalized_json=json.dumps(normalized),
    )
    db.add(upload)
    session = get_session(db, session_id, with_relations=False)
    session.updated_at = utcnow()
    db.commit()
    db.refresh(upload)
    return upload


def get_latest_upload(db: Session, session_id: int) -> UploadedDataModel | None:
    stmt = (
        select(UploadedDataModel)
        .where(UploadedDataModel.session_id == session_id)
        .order_by(UploadedDataModel.created_at.desc())
        .limit(1)
    )
    return db.scalars(stmt).first()


def upload_to_dict(upload: UploadedDataModel) -> dict:
    return {
        "id": upload.id,
        "session_id": upload.session_id,
        "filename": upload.filename,
        "content_type": upload.content_type,
        "created_at": upload.created_at,
        "preview": preview_text(upload.raw_text),
    }


def session_to_summary(session: SessionModel) -> dict:
    return {
        "id": session.id,
        "title": session.title,
        "created_at": session.created_at,
        "updated_at": session.updated_at,
        "message_count": len(session.messages) if session.messages is not None else 0,
        "upload_count": len(session.uploads) if session.uploads is not None else 0,
    }
