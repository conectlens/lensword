"""Redacted observability events for the diagnosis pipeline (#181 TODO 4).

Every event type here is deliberately missing the fields that would leak a
learner's answer or the vocabulary context around it — not filtered out at
log time, but never present on the type at all. A logging call reaching for
`observation.attempted_answer` on one of these simply gets an
`AttributeError`, which is a stronger guarantee than a redaction filter that
has to remember every sensitive key name and can miss a new one.

The five events named in the issue: one factory function each, projecting
from the rich domain contract (which does carry the sensitive fields) to the
safe event (which cannot). No logger call lives here — this module defines
what is safe to hand to one, not how logging is wired up, which is an
infrastructure concern this phase does not touch.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime

from app.domain.services.diagnosis_contracts import (
    Diagnosis,
    InterventionOutcome,
    InterventionPlan,
    LearningObservation,
)


@dataclass(frozen=True, slots=True)
class ObservationRecordedEvent:
    observation_id: str
    word_id: int
    user_id: int
    outcome: str
    session_mode: str
    schema_version: int
    recorded_at: datetime


@dataclass(frozen=True, slots=True)
class DiagnosisProducedEvent:
    word_id: int
    user_id: int
    outcome: str
    evidence_count: int
    confidence: float | None
    rules_version: int
    produced_at: datetime


@dataclass(frozen=True, slots=True)
class InterventionScheduledEvent:
    word_id: int
    user_id: int
    strategy: str
    policy_version: int
    eligible: bool
    scheduled_at: datetime


@dataclass(frozen=True, slots=True)
class InterventionCompletedEvent:
    word_id: int
    user_id: int
    strategy: str
    completed: bool
    result: str
    recorded_at: datetime


@dataclass(frozen=True, slots=True)
class DiagnosisCorrectedEvent:
    word_id: int
    user_id: int
    previous_outcome: str
    corrected_outcome: str
    rules_version: int
    corrected_at: datetime


def observation_recorded_event(observation: LearningObservation) -> ObservationRecordedEvent:
    return ObservationRecordedEvent(
        observation_id=observation.observation_id,
        word_id=observation.word_id,
        user_id=observation.user_id,
        outcome=observation.outcome.value,
        session_mode=observation.session_mode.value,
        schema_version=observation.schema_version,
        recorded_at=observation.observed_at,
    )


def diagnosis_produced_event(diagnosis: Diagnosis) -> DiagnosisProducedEvent:
    return DiagnosisProducedEvent(
        word_id=diagnosis.word_id,
        user_id=diagnosis.user_id,
        outcome=diagnosis.outcome,
        evidence_count=len(diagnosis.evidence),
        confidence=diagnosis.confidence,
        rules_version=diagnosis.rules_version,
        produced_at=diagnosis.diagnosed_at,
    )


def intervention_scheduled_event(plan: InterventionPlan) -> InterventionScheduledEvent:
    return InterventionScheduledEvent(
        word_id=plan.word_id,
        user_id=plan.user_id,
        strategy=plan.strategy,
        policy_version=plan.policy_version,
        eligible=plan.eligible,
        scheduled_at=plan.planned_at,
    )


def intervention_completed_event(outcome: InterventionOutcome) -> InterventionCompletedEvent:
    return InterventionCompletedEvent(
        word_id=outcome.word_id,
        user_id=outcome.user_id,
        strategy=outcome.strategy,
        completed=outcome.completed,
        result=outcome.result,
        recorded_at=outcome.recorded_at,
    )


def diagnosis_corrected_event(
    previous: Diagnosis, corrected: Diagnosis, corrected_at: datetime
) -> DiagnosisCorrectedEvent:
    return DiagnosisCorrectedEvent(
        word_id=corrected.word_id,
        user_id=corrected.user_id,
        previous_outcome=previous.outcome,
        corrected_outcome=corrected.outcome,
        rules_version=corrected.rules_version,
        corrected_at=corrected_at,
    )


# Every field name a redacted event must never carry, regardless of which
# event type — used by the log-safety test to fail loudly if a future field
# addition reintroduces one, rather than relying on the event's current
# shape staying accidentally safe.
FORBIDDEN_FIELD_NAMES = frozenset({
    "attempted_answer",
    "term",
    "translation",
    "translations",
    "example_sentence",
    "mnemonic",
    "context_source",
    "self_reported_confidence",
})


def as_loggable_dict(event: object) -> dict:
    """The only sanctioned way to turn one of these events into something a
    logger can serialize — asserts the forbidden fields are absent rather
    than trusting the caller picked a safe event type."""
    payload = asdict(event)
    leaked = FORBIDDEN_FIELD_NAMES & payload.keys()
    if leaked:
        raise ValueError(f"refusing to log fields that may carry learner text: {sorted(leaked)}")
    return payload
