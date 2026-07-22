from datetime import datetime

from pydantic import BaseModel, Field

from app.api.schemas.vocabulary import WordResponse
from app.domain.value_objects import ReviewOutcome, SessionMode


class StartReviewSessionRequest(BaseModel):
    mode: SessionMode = SessionMode.STANDARD
    group_id: int | None = None
    limit: int = Field(default=20, ge=1, le=100)


class StartReviewSessionResponse(BaseModel):
    session_id: int
    mode: SessionMode
    words: list[WordResponse]


class SubmitAnswerRequest(BaseModel):
    word_id: int
    outcome: ReviewOutcome
    response_time_ms: int | None = None


class SubmitAnswerResponse(BaseModel):
    word: WordResponse
    was_new_word_learned: bool


class CompleteSessionRequest(BaseModel):
    new_words_learned_count: int = 0


class SessionSummaryResponse(BaseModel):
    id: int
    mode: SessionMode
    started_at: datetime
    ended_at: datetime | None
    duration_seconds: int
    words_reviewed: int
    correct_count: int
    incorrect_count: int
    new_words_learned: int
    accuracy_percent: float


class WeeklyProgressResponse(BaseModel):
    counts_by_day: dict[str, int]


class MnemonicCreateRequest(BaseModel):
    text: str = Field(min_length=1, max_length=1000)


class MnemonicVoteRequest(BaseModel):
    upvote: bool = True


class MnemonicResponse(BaseModel):
    id: int
    word_id: int
    author_id: int
    text: str
    is_ai_generated: bool
    upvotes: int
    downvotes: int
    score: int
    created_at: datetime
