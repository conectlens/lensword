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


class ContrastCardResponse(BaseModel):
    """A pair shown together; it is not an independently scheduled item."""

    word_ids: tuple[int, int]
    terms: tuple[str, str]
    relation: str
    prompt: str


class ContrastAnswerRequest(BaseModel):
    word_ids: tuple[int, int]
    terms: tuple[str, str]
    relation: str
    prompt: str
    first_word_note: str = Field(min_length=1, max_length=1000)
    second_word_note: str = Field(min_length=1, max_length=1000)
    distinction: str = Field(min_length=1, max_length=1000)


class ContrastAnswerResponse(BaseModel):
    accepted: bool = True
    scheduled: bool = False


class SubmitAnswerRequest(BaseModel):
    word_id: int
    outcome: ReviewOutcome
    response_time_ms: int | None = None
    # What the learner actually typed, when the client collects it (#134).
    # Optional: a flashcard client that only reports right/wrong stays valid,
    # and the mistake is still recorded — just without the confusion pair,
    # which cannot be inferred from an outcome alone.
    attempted_answer: str | None = None
    # Everything below is #182's richer telemetry, all optional so an
    # existing client stays valid unmodified. None of it is read unless
    # the account has learning_diagnosis_enabled on (ADR 0007).
    #
    # Client-generated and stable across retries — the same idempotency
    # contract issue #90's sync submission already uses.
    operation_id: str | None = Field(default=None, max_length=64)
    prompt_direction: str | None = Field(default=None, max_length=32)
    hint_used: bool = False
    answer_format: str | None = Field(default=None, max_length=32)
    modality: str | None = Field(default=None, max_length=32)
    intervention_plan_ref: str | None = Field(default=None, max_length=64)
    # Only ever the learner's own stated confidence — never populated from
    # an AI guess (ADR 0007).
    self_reported_confidence: float | None = Field(default=None, ge=0, le=1)


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
