from pydantic import BaseModel

from app.api.schemas.auth import UserResponse


class AdminStatsResponse(BaseModel):
    total_users: int
    new_users_last_30_days: int
    total_words_learned: int
    active_sessions_last_hour: int


class AdminUserListResponse(BaseModel):
    users: list[UserResponse]
    total: int
