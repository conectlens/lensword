"""Application-layer orchestration for measurable companion activities
(#194).

`app.domain.services.companion_activities` stays pure — no repositories, no
clocks, no idea `LearningObservation` even exists. Everything here does the
I/O: validating an activity's word target against the learner's own
vocabulary at creation time (so the evaluation rule really is fixed before
any response exists), and wiring a graded activity's result into a real
`LearningObservation` exactly once — reusing #182's existing
observation-recording path (`LearningObservationRepository`, the same
find-by-operation-before-add idempotency `RecordContextOccurrenceUseCase`
already uses in `mcp_dev_workflow.py`), not a new one.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.application.use_cases.mcp_dev_workflow import ExplainWordForUserUseCase, WordExplanation
from app.application.use_cases.vocabulary import _require_word_owner
from app.domain.exceptions import EntityNotFoundError, ValidationError
from app.domain.repositories import (
    CompanionActivityRepository,
    DiagnosisRepository,
    GroupRepository,
    LearningObservationRepository,
    WordRepository,
)
from app.domain.services.companion_activities import (
    ActivityType,
    LearningActivity,
    creates_observation,
    evaluate_response,
)
from app.domain.services.diagnosis_contracts import LearningObservation
from app.domain.value_objects import ReviewOutcome, SessionMode, utcnow


def observation_operation_id(activity: LearningActivity) -> str:
    """Derived, deterministic, and independent of any client-supplied
    `operation_id` — the same activity can only ever be the source of one
    observation no matter how many times its submission is retried (#194
    TODO 5): a caller replaying `submit_activity_response` finds the same
    row via `LearningObservationRepository.find_by_operation` rather than
    inserting a second one.
    """
    return f"companion-activity:{activity.id}"


class BeginLearningActivityUseCase:
    """Fixes and validates an activity's evaluation rule at creation time.

    `expected_evaluation["word_id"]`, when present, must name a word the
    learner actually owns — checked once, here, before the activity is ever
    persisted. Nothing downstream can change `expected_evaluation`
    afterward: `LearningActivity` has no setter for it, only `submit()`,
    which writes the learner's response and the evaluator's result, never
    the rule it was evaluated against. That is what makes it structurally
    impossible — not merely policy — for the companion to submit an
    expected answer after seeing the learner's response.
    """

    def __init__(self, word_repo: WordRepository, group_repo: GroupRepository):
        self.word_repo = word_repo
        self.group_repo = group_repo

    def validate(self, user_id: int, activity_type: ActivityType, expected_evaluation: dict) -> None:
        if activity_type is ActivityType.FREE_CHAT:
            return
        word_id = expected_evaluation.get("word_id")
        if word_id is None:
            return
        if not isinstance(word_id, int) or isinstance(word_id, bool):
            raise ValidationError("expected_evaluation.word_id must be an integer")
        _require_word_owner(self.word_repo, self.group_repo, word_id, user_id)


@dataclass(frozen=True, slots=True)
class ActivitySubmissionResult:
    activity: LearningActivity
    observation: LearningObservation | None


def _outcome_for_result(result: dict) -> ReviewOutcome:
    correct = result.get("correct")
    if correct is True:
        return ReviewOutcome.CORRECT
    if correct is False:
        return ReviewOutcome.INCORRECT
    return ReviewOutcome.CORRECT if result.get("non_empty") else ReviewOutcome.SKIPPED


class SubmitActivityResponseUseCase:
    """Evaluates a learner's response and, only for a structured activity
    the domain layer's `creates_observation` says should count, records
    exactly one `LearningObservation` (#194 TODO 0) — the single most
    important wiring this issue adds. Free chat and any activity explicitly
    flagged `"ungraded"`/`"praise"` in its `expected_evaluation` never reach
    `observation_repo.add`, and an activity with no `word_id` in its fixed
    evaluation rule has nothing to attach evidence to, so it produces none
    either rather than one built on a fabricated word.
    """

    def __init__(
        self,
        activity_repo: CompanionActivityRepository,
        observation_repo: LearningObservationRepository,
    ):
        self.activity_repo = activity_repo
        self.observation_repo = observation_repo

    def execute(self, user_id: int, activity: LearningActivity, response_text: str) -> ActivitySubmissionResult:
        result = evaluate_response(activity, response_text)
        activity.submit(response_text, result)
        saved = self.activity_repo.update(activity)

        if not creates_observation(saved.activity_type, saved.expected_evaluation):
            return ActivitySubmissionResult(activity=saved, observation=None)

        word_id = saved.expected_evaluation.get("word_id")
        if not isinstance(word_id, int) or isinstance(word_id, bool):
            return ActivitySubmissionResult(activity=saved, observation=None)

        operation_id = observation_operation_id(saved)
        existing = self.observation_repo.find_by_operation(user_id, operation_id)
        if existing is not None:
            return ActivitySubmissionResult(activity=saved, observation=existing)

        observation = LearningObservation(
            observation_id=uuid.uuid4().hex,
            word_id=word_id,
            user_id=user_id,
            outcome=_outcome_for_result(result),
            session_mode=SessionMode.STANDARD,
            observed_at=utcnow(),
            operation_id=operation_id,
            attempted_answer=(saved.response or "")[:255],
            hint_used=saved.hints_used > 0,
            answer_format="companion_activity",
            modality=saved.activity_type.value,
            # A bounded, joinable pointer back to the activity that produced
            # this observation: querying `companion_activities` by
            # `operation_id` (`companion-activity:{activity.id}`) recovers
            # the full prompt/evaluator/session/client trail without
            # duplicating any of it onto this append-only row.
            context_source=f"companion_activity:{saved.activity_type.value}"[:64],
        )
        saved_observation = self.observation_repo.add(observation)
        return ActivitySubmissionResult(activity=saved, observation=saved_observation)


class RequestActivityHintUseCase:
    """A bounded, deterministic nudge (#194 TODO 1's `request_hint`), built
    only from facts the learner already has access to elsewhere (the
    target word's own category/part of speech/CEFR level) — never the
    `expected_answer` itself, and never an AI call, so it always works
    offline the same way `ExplainWordForUserUseCase` does.
    """

    def __init__(
        self,
        activity_repo: CompanionActivityRepository,
        word_repo: WordRepository,
        group_repo: GroupRepository,
    ):
        self.activity_repo = activity_repo
        self.word_repo = word_repo
        self.group_repo = group_repo

    def execute(self, user_id: int, activity: LearningActivity) -> tuple[LearningActivity, str]:
        hint = self._build_hint(user_id, activity)
        activity.request_hint()
        saved = self.activity_repo.update(activity)
        return saved, hint

    def _build_hint(self, user_id: int, activity: LearningActivity) -> str:
        word_id = activity.expected_evaluation.get("word_id")
        if not isinstance(word_id, int) or isinstance(word_id, bool):
            return "No additional hint is available for this activity."
        word = _require_word_owner(self.word_repo, self.group_repo, word_id, user_id)
        details = [
            part
            for part in (
                f"a {word.part_of_speech}" if word.part_of_speech else None,
                f"category '{word.category}'" if word.category else None,
                f"CEFR level {word.cefr_level}" if word.cefr_level else None,
            )
            if part
        ]
        if not details:
            return f"This targets a {word.target_language.value} word you have already added."
        return "This targets " + ", ".join(details) + "."


class ExplainActivityEvidenceUseCase:
    """Explains, deterministically and without an AI call, why an activity
    was scored the way it was (#194 TODO 1's `explain_evidence`) —
    reusing #185's diagnosis-grounded `ExplainWordForUserUseCase` for the
    word-level evidence rather than re-deriving it, plus the activity's own
    recorded facts (prompt, evaluator, result, hints used).
    """

    def __init__(
        self,
        word_repo: WordRepository,
        group_repo: GroupRepository,
        diagnosis_repo: DiagnosisRepository,
    ):
        self.explain_word = ExplainWordForUserUseCase(word_repo, group_repo, diagnosis_repo)

    def execute(self, user_id: int, activity: LearningActivity) -> dict:
        evidence: dict = {
            "activity_id": activity.id,
            "activity_type": activity.activity_type.value,
            "prompt": activity.prompt,
            "status": activity.status.value,
            "result": activity.result,
            "hints_used": activity.hints_used,
            "word_explanation": None,
        }
        word_id = activity.expected_evaluation.get("word_id")
        if isinstance(word_id, int) and not isinstance(word_id, bool):
            try:
                explanation: WordExplanation = self.explain_word.execute(user_id, word_id)
            except EntityNotFoundError:
                explanation = None
            if explanation is not None:
                evidence["word_explanation"] = {
                    "word_id": explanation.word_id,
                    "term": explanation.term,
                    "has_diagnosis": explanation.has_diagnosis,
                    "diagnosis_outcome": explanation.diagnosis_outcome,
                    "diagnosis_confidence": explanation.diagnosis_confidence,
                    "sample_size": explanation.sample_size,
                    "explanation": explanation.explanation,
                }
        return evidence
