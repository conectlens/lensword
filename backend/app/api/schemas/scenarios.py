"""Scenario role-play requests and responses (issue #136)."""
from datetime import datetime

from pydantic import BaseModel, Field

from app.domain.services.conversation import Difficulty


class ScenarioResponse(BaseModel):
    key: str
    title: str
    # Shown to the learner. The tutor's role is deliberately absent: they are
    # never shown the instruction the model is given.
    briefing: str
    goals: list[str]
    suggested_topics: list[str]


class StartAttemptRequest(BaseModel):
    scenario_key: str = Field(min_length=1, max_length=64)
    target_language: str = Field(min_length=1, max_length=32)
    difficulty: Difficulty = Difficulty.STEADY


class ScenarioAttemptResponse(BaseModel):
    id: int
    # Turns go through the existing conversation endpoint, so the client needs
    # this to send them. One transport, not two.
    session_id: int
    scenario: ScenarioResponse
    started_at: datetime
    finished_at: datetime | None
    # Null until finished. Stays null-ish (`scored: false`) when the attempt was
    # too short to judge — different from a zero, which would claim the learner
    # did badly rather than admit we cannot tell.
    evaluation: dict | None
