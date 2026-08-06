"""Bounded measurable companion activities (#194).

Free chat remains outside this model. Only an explicitly started activity with
a known type and prompt can receive a response, and its result is a structured
record rather than a mastery update.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from datetime import datetime


class ActivityType(str, Enum):
    FREE_CHAT = "free_chat"
    RECALL = "recall"
    CLOZE = "cloze"
    CONTRAST = "contrast"
    TRANSLATION = "translation"
    EXPLANATION = "explanation"
    WRITING = "writing"
    LISTENING = "listening"
    REFLECTION = "reflection"


class ActivityStatus(str, Enum):
    ACTIVE = "active"
    SUBMITTED = "submitted"
    FINISHED = "finished"
    CANCELLED = "cancelled"


@dataclass(slots=True)
class LearningActivity:
    id: str
    session_id: str
    user_id: int
    activity_type: ActivityType
    prompt: str
    expected_evaluation: dict
    status: ActivityStatus
    response: str | None
    result: dict | None
    operation_id: str | None
    started_at: datetime
    updated_at: datetime
    revision: int = 1

    def submit(self, response: str, result: dict) -> None:
        if self.status is not ActivityStatus.ACTIVE:
            raise ValueError("Activity is no longer accepting a response")
        if not response.strip() or len(response) > 10000:
            raise ValueError("Activity response must contain 1-10000 characters")
        self.response = response
        self.result = result
        self.status = ActivityStatus.SUBMITTED
        self.revision += 1

    def finish(self) -> None:
        if self.status not in {ActivityStatus.SUBMITTED, ActivityStatus.CANCELLED}:
            raise ValueError("Only submitted or cancelled activities can finish")
        self.status = ActivityStatus.FINISHED
        self.revision += 1

    def cancel(self) -> None:
        if self.status is not ActivityStatus.ACTIVE:
            raise ValueError("Only active activities can be cancelled")
        self.status = ActivityStatus.CANCELLED
        self.revision += 1


def evaluate_response(activity: LearningActivity, response: str) -> dict:
    """Return bounded factual evaluation metadata, never a mastery score."""
    normalized = response.strip()
    return {
        "evaluator": "deterministic_presence_v1",
        "response_length": len(normalized),
        "non_empty": bool(normalized),
        "activity_type": activity.activity_type.value,
    }
