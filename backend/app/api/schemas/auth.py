from datetime import date, datetime

from pydantic import BaseModel, EmailStr, Field

from app.domain.value_objects import UserRole


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: int
    username: str
    email: str
    role: UserRole
    created_at: datetime
    streak_days: int
    longest_streak_days: int
    last_activity_date: date | None
    total_words_learned: int
    total_study_seconds: int
    is_active: bool


class AuthenticatedResponse(BaseModel):
    user: UserResponse
    token: TokenResponse
