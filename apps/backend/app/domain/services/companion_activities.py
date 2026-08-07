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


# A hint is a small nudge, not a way to grind the answer out of the
# companion one letter at a time — bounded the same way MAX_CORRECTIONS_PER_TURN
# bounds corrections in app.domain.services.conversation.
MAX_HINTS_PER_ACTIVITY = 3


@dataclass(slots=True)
class LearningActivity:
    id: str
    session_id: str
    user_id: int
    activity_type: ActivityType
    prompt: str
    # The evaluation rule (e.g. `{"word_id": 7, "expected_answer": "gato"}`)
    # fixed once at construction time. Nothing on this class can change it
    # after the fact — no `set_expected_evaluation`, no parameter on
    # `submit` — which is what makes it structurally impossible for the
    # companion to submit an expected answer after seeing the learner's
    # response (#194 TODO 5).
    expected_evaluation: dict
    status: ActivityStatus
    response: str | None
    result: dict | None
    operation_id: str | None
    started_at: datetime
    updated_at: datetime
    revision: int = 1
    hints_used: int = 0

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

    def request_hint(self) -> int:
        """Record that one more hint was used and return the new count.

        Only while the activity is still active and only up to
        `MAX_HINTS_PER_ACTIVITY` — an activity already submitted/finished/
        cancelled has nothing left to hint about, and an unbounded number of
        hints would let a "structured recall" activity be answered entirely
        by the companion instead of the learner.
        """
        if self.status is not ActivityStatus.ACTIVE:
            raise ValueError("Hints can only be requested while an activity is active")
        if self.hints_used >= MAX_HINTS_PER_ACTIVITY:
            raise ValueError("Maximum hints for this activity have already been used")
        self.hints_used += 1
        self.revision += 1
        return self.hints_used


def _normalize(text: str) -> str:
    return " ".join(text.split()).casefold()


def evaluate_response(activity: LearningActivity, response: str) -> dict:
    """Return bounded factual evaluation metadata, never a mastery score.

    `expected_evaluation` was fixed at `begin_learning_activity` time and is
    read-only from here — this function has no way to write it, so it
    cannot be used to smuggle a post-hoc "expected answer" into an activity
    after the learner has already answered (#194 TODO 5).

    When the fixed rule names a single `expected_answer` (or a bounded list
    of acceptable ones), a plain case/whitespace-insensitive comparison adds
    a factual `"correct"` key. This is still not a mastery judgement — it is
    a deterministic string comparison against a rule the caller supplied
    before the response existed, same posture as the rest of this module.
    """
    normalized = response.strip()
    result = {
        "evaluator": "deterministic_presence_v1",
        "response_length": len(normalized),
        "non_empty": bool(normalized),
        "activity_type": activity.activity_type.value,
    }
    expected_answer = activity.expected_evaluation.get("expected_answer")
    candidates: set[str] = set()
    if isinstance(expected_answer, str) and expected_answer.strip():
        candidates = {_normalize(expected_answer)}
    elif isinstance(expected_answer, list):
        candidates = {
            _normalize(item) for item in expected_answer[:20] if isinstance(item, str) and item.strip()
        }
    if candidates:
        result["correct"] = _normalize(normalized) in candidates
    return result


def creates_observation(activity_type: ActivityType, expected_evaluation: dict) -> bool:
    """Only a structured activity's result may ever become a
    `LearningObservation` (#194 TODO 0) — the boundary the issue calls out
    as the single most important fix: free chat and AI praise never count
    as mastery evidence.

    - `ActivityType.FREE_CHAT` never creates one, unconditionally.
    - Any activity type whose fixed `expected_evaluation` was marked
      `"ungraded": true` or `"praise": true` at `begin_learning_activity`
      time never creates one either — the companion offering unscored
      encouragement mid-activity must not silently become evidence.
    - Every other structured activity does.
    """
    if activity_type is ActivityType.FREE_CHAT:
        return False
    if bool(expected_evaluation.get("ungraded")) or bool(expected_evaluation.get("praise")):
        return False
    return True
