"""Graduated acquisition ladder responses (#180, issue #184)."""
from datetime import datetime

from pydantic import BaseModel, Field

from app.domain.value_objects import ReviewOutcome


class AcquisitionStateResponse(BaseModel):
    word_id: int
    rung: int
    ladder_version: int
    started_at: datetime
    updated_at: datetime
    due_at: datetime
    graduated: bool
    # Why this ladder started (TODO 3: "show why the item entered
    # acquisition mode") — null only for a state this account somehow
    # never recorded a reason for.
    entry_reason: str | None


class AcquisitionAnswerRequest(BaseModel):
    outcome: ReviewOutcome
    operation_id: str | None = Field(default=None, max_length=64)
