from datetime import datetime
from typing import Annotated, Literal

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


class MnemonicSuggestionDisabled(BaseModel):
    """No AI provider is configured. A deployment setting, not a fault — the
    client shows a calm notice, never an error."""

    status: Literal["disabled"] = "disabled"


class MnemonicSuggestionUnavailable(BaseModel):
    """A provider is configured but could not be reached or used. Transient,
    so the client offers a retry."""

    status: Literal["unavailable"] = "unavailable"
    detail: str


class MnemonicSuggestionOk(BaseModel):
    status: Literal["ok"] = "ok"
    text: str


# Discriminated on `status` so the client can branch on a field instead of
# pattern-matching an error message, and so OpenAPI documents the three
# shapes separately.
MnemonicSuggestionResponse = Annotated[
    MnemonicSuggestionDisabled | MnemonicSuggestionUnavailable | MnemonicSuggestionOk,
    Field(discriminator="status"),
]
