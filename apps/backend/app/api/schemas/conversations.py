"""Conversation tutor requests and responses (issue #135)."""
from datetime import datetime

from pydantic import BaseModel, Field

from app.domain.services.conversation import Difficulty


class StartConversationRequest(BaseModel):
    target_language: str = Field(min_length=1, max_length=32)
    difficulty: Difficulty = Difficulty.STEADY
    group_id: int | None = None
    # Free text describing the situation, when there is one. Present from the
    # start because scenario role-play (#136) uses this same transport.
    scenario: str | None = Field(default=None, max_length=120)


class SendMessageRequest(BaseModel):
    # Bounded: it is stored and sent to a model, so an unbounded message is a
    # way to push the rest of the prompt out of the window.
    text: str = Field(min_length=1, max_length=2000)


class CorrectionResponse(BaseModel):
    # Always a substring of what the learner actually wrote — validated before
    # storage, because a highlight pointing at words nobody typed teaches the
    # learner to ignore highlights entirely.
    original: str
    corrected: str
    explanation: str


class MessageResponse(BaseModel):
    id: int
    speaker: str
    text: str
    corrections: list[CorrectionResponse]
    created_at: datetime


class ConversationResponse(BaseModel):
    id: int
    target_language: str
    difficulty: str
    scenario: str | None
    group_id: int | None
    created_at: datetime
    ended_at: datetime | None
    messages: list[MessageResponse]


class SendMessageResponse(BaseModel):
    # "ok", "disabled" or "unavailable". A provider switched off or temporarily
    # down is a normal state of a healthy install, not a server error.
    status: str
    # The learner's own turn, stored regardless of whether the tutor answered —
    # losing what someone typed because a model was down is the one outcome
    # that makes a chat feel broken.
    learner_message: MessageResponse | None = None
    tutor_message: MessageResponse | None = None
    detail: str | None = None
