"""Company data upload routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.database import get_db
from app.models.schemas import UploadResponse, UploadedDataOut
from app.services.file_service import (
    FileServiceError,
    parse_and_normalize,
    validate_upload,
)
from app.services import session_service
from app.services.session_service import SessionNotFoundError

router = APIRouter(prefix="/sessions", tags=["uploads"])


@router.post("/{session_id}/upload", response_model=UploadResponse)
async def upload_company_data(
    session_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> UploadResponse:
    settings = get_settings()
    filename = file.filename or "upload.bin"
    raw = await file.read()

    try:
        validate_upload(filename, raw, settings.max_upload_bytes)
        normalized = parse_and_normalize(filename, raw)
        text = raw.decode("utf-8-sig")
        upload = session_service.save_upload(
            db,
            session_id=session_id,
            filename=filename,
            content_type=file.content_type or "application/octet-stream",
            raw_text=text,
            normalized=normalized,
        )
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except FileServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="File must be UTF-8 encoded.") from exc

    summary = {
        "format": normalized.get("format"),
        "record_count": normalized.get("record_count"),
        "fields": normalized.get("fields"),
        "summary_stats": normalized.get("summary_stats"),
    }
    return UploadResponse(
        upload=UploadedDataOut(**session_service.upload_to_dict(upload)),
        summary=summary,
        message=f"Uploaded {filename} and attached it to this boardroom session.",
    )
