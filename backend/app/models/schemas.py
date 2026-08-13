"""Pydantic request/response schemas for the Boardroom API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class SessionCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)


class SessionUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=255)


class SessionOut(BaseModel):
    id: int
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int = 0
    upload_count: int = 0

    model_config = {"from_attributes": True}


class MessageOut(BaseModel):
    id: int
    session_id: int
    speaker: str
    role: str
    content: str
    round: int | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class UploadedDataOut(BaseModel):
    id: int
    session_id: int
    filename: str
    content_type: str
    created_at: datetime
    preview: str | None = None

    model_config = {"from_attributes": True}


class SessionDetail(SessionOut):
    messages: list[MessageOut] = []
    uploads: list[UploadedDataOut] = []


class CEOMessageRequest(BaseModel):
    question: str = Field(min_length=1, max_length=8000)
    title_hint: str | None = Field(default=None, max_length=255)


class DiscussionEntry(BaseModel):
    role: str
    round: int
    content: str


class BoardSynthesis(BaseModel):
    recommendation: str
    key_risks: list[str] = []
    disagreements: list[str] = []
    actions: list[str] = []
    metrics: list[str] = []
    confidence: Literal["High", "Medium", "Low"] = "Medium"


class BoardResponse(BaseModel):
    session_id: int
    question: str
    discussion: list[DiscussionEntry]
    synthesis: BoardSynthesis
    messages: list[MessageOut] = []


class UploadResponse(BaseModel):
    upload: UploadedDataOut
    summary: dict[str, Any]
    message: str


class HealthResponse(BaseModel):
    status: str
    openai_configured: bool
    model: str
    llm_mode: Literal["demo", "openai"] = "openai"


class ErrorResponse(BaseModel):
    detail: str
