"""Learning path requests and responses (issue #137)."""
from datetime import datetime

from pydantic import BaseModel, Field


class GeneratePathRequest(BaseModel):
    # Free text, and bounded: it is stored, displayed, and sent to a model, so
    # an unbounded goal is a way to push everything else out of a prompt.
    goal: str = Field(min_length=1, max_length=500)
    target_language: str = Field(min_length=1, max_length=32)
    group_id: int | None = None


class MilestoneResponse(BaseModel):
    position: int
    title: str
    description: str
    topic: str
    target_word_count: int
    cefr_level: str | None
    # Counted from the learner's deck at read time, never stored — a saved
    # count is a number that was true once.
    words_held: int
    words_mastered: int
    complete: bool
    share: float


class LearningPathResponse(BaseModel):
    id: int
    goal: str
    target_language: str
    group_id: int | None
    ai_provider: str | None
    ai_model: str | None
    created_at: datetime
    milestones: list[MilestoneResponse]
    completed_count: int
    share: float
    # The first unfinished step — what the learner is actually being asked to
    # do next. Null when the path is finished.
    next_milestone: MilestoneResponse | None


class GeneratePathResponse(BaseModel):
    # "ok", "disabled" or "unavailable". Mirrors the mnemonic endpoint: a
    # provider switched off or temporarily down is a normal state of a healthy
    # install rather than a server error.
    status: str
    path: LearningPathResponse | None = None
    detail: str | None = None
