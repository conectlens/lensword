"""Provider-neutral companion session API contracts (#193)."""
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.domain.services.companion_sessions import CompanionSessionStatus, CompanionTurnRole


class CompanionSessionCreateRequest(BaseModel):
    connection_id: str = Field(min_length=1, max_length=128)
    client_id: str = Field(min_length=1, max_length=128)
    goal: str | None = Field(default=None, max_length=500)
    language: str | None = Field(default=None, max_length=64)
    group_id: int | None = Field(default=None, ge=1)
    difficulty: str | None = Field(default=None, max_length=32)
    active_activity: str | None = Field(default=None, max_length=128)
    consent_snapshot: dict[str, Any] = Field(default_factory=dict)


class CompanionTurnRequest(BaseModel):
    role: CompanionTurnRole
    content: str = Field(min_length=1, max_length=10000)
    activity_id: str | None = Field(default=None, max_length=128)
    operation_id: str | None = Field(default=None, max_length=128)


class CompanionTurnResponse(BaseModel):
    id: int
    session_id: str
    role: CompanionTurnRole
    content: str
    activity_id: str | None
    operation_id: str | None
    created_at: datetime


class CompanionSessionResponse(BaseModel):
    id: str
    connection_id: str
    client_id: str
    goal: str | None
    language: str | None
    group_id: int | None
    difficulty: str | None
    active_activity: str | None
    consent_snapshot: dict[str, Any]
    summary: str | None
    status: CompanionSessionStatus
    revision: int
    created_at: datetime
    updated_at: datetime
    turns: list[CompanionTurnResponse] = []


class CompanionExportResponse(BaseModel):
    session: CompanionSessionResponse
    format: str = "lensword.companion-session.v1"


class CompanionActionResponse(BaseModel):
    session: CompanionSessionResponse


class CompanionActivityCreateRequest(BaseModel):
    activity_type: str = Field(min_length=1, max_length=32)
    prompt: str = Field(min_length=1, max_length=4000)
    expected_evaluation: dict[str, Any] = Field(default_factory=dict)
    operation_id: str | None = Field(default=None, max_length=128)


class CompanionActivityResponse(BaseModel):
    id: str
    session_id: str
    activity_type: str
    prompt: str
    expected_evaluation: dict[str, Any]
    status: str
    response: str | None
    result: dict[str, Any] | None
    operation_id: str | None
    started_at: datetime
    updated_at: datetime
    revision: int


class CompanionActivityAnswerRequest(BaseModel):
    response: str = Field(min_length=1, max_length=10000)
