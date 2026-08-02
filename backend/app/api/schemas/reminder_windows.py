"""Request/response shapes for reminder-window recommendations (issue #89)."""
from __future__ import annotations

from pydantic import BaseModel, Field


class ReminderWindowRecommendationResponse(BaseModel):
    reminder_id: int
    current_hour: int
    suggested_hour: int
    # Both rates and both sample sizes travel to the client, rather than a
    # single confidence score. The user is being asked to change when they are
    # interrupted, so the evidence should be inspectable rather than reduced to
    # a verdict.
    suggested_rate: float
    current_rate: float
    suggested_sample: int
    current_sample: int
    explanation: str


class ReminderWindowResponse(BaseModel):
    # Null is the ordinary answer: most accounts, most of the time, do not have
    # enough evidence for a suggestion.
    recommendation: ReminderWindowRecommendationResponse | None


class AcceptReminderWindowRequest(BaseModel):
    # Echoed back by the client so the server can confirm the user is accepting
    # the suggestion they were shown, not one that has since changed.
    hour: int = Field(ge=0, le=23)
