from pydantic import BaseModel
from pydantic import Field
from datetime import datetime

from app.api.schemas.auth import UserResponse


class AdminStatsResponse(BaseModel):
    total_users: int
    new_users_last_30_days: int
    total_words_learned: int
    active_sessions_last_hour: int


class AdminUserListResponse(BaseModel):
    users: list[UserResponse]
    total: int


class MCPGrantRequest(BaseModel):
    requester: str = Field(min_length=1, max_length=255)
    server: str = Field(min_length=1, max_length=255)
    tool: str = Field(min_length=1, max_length=255)
    access: str = Field(pattern="^(read|write|high_impact|destructive)$")
    workspace: str = Field(min_length=1, max_length=1024)
    mode: str = Field(pattern="^(once|always|deny)$")
    expires_at: datetime | None = None


class MCPGrantResponse(MCPGrantRequest):
    id: int
    revoked_at: datetime | None


class MCPAuditResponse(BaseModel):
    id: int
    requester: str
    tool: str
    decision: str
    event: dict
    event_hash: str
    created_at: datetime
