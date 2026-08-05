"""Redacted diagnosis events (#181 TODO 4).

Verify step from the issue: automated log tests confirm secrets and raw
answer text are absent. These build a rich domain object carrying a real
answer string, derive the corresponding event, and assert that string is
nowhere in the loggable output — not filtered out, structurally impossible
to have been present.
"""
from __future__ import annotations

from datetime import datetime

from app.domain.services.diagnosis_contracts import Diagnosis, InterventionOutcome, InterventionPlan, LearningObservation
from app.domain.services.diagnosis_events import (
    FORBIDDEN_FIELD_NAMES,
    as_loggable_dict,
    diagnosis_corrected_event,
    diagnosis_produced_event,
    intervention_completed_event,
    intervention_scheduled_event,
    observation_recorded_event,
)
from app.domain.value_objects import ReviewOutcome, SessionMode

NOW = datetime(2026, 8, 6, 9, 0)
SECRET_ANSWER = "un-secreto-que-nunca-deberia-aparecer-en-los-logs"


def test_observation_recorded_event_never_carries_the_attempted_answer():
    observation = LearningObservation(
        observation_id="obs-1",
        word_id=1,
        user_id=1,
        outcome=ReviewOutcome.INCORRECT,
        session_mode=SessionMode.STANDARD,
        observed_at=NOW,
        attempted_answer=SECRET_ANSWER,
        self_reported_confidence=0.3,
    )
    event = observation_recorded_event(observation)
    payload = as_loggable_dict(event)

    assert SECRET_ANSWER not in repr(payload)
    assert "attempted_answer" not in payload
    assert "self_reported_confidence" not in payload


def test_diagnosis_produced_event_carries_a_count_not_the_evidence_text():
    from app.domain.services.diagnosis_contracts import DiagnosisEvidence

    diagnosis = Diagnosis(
        word_id=1,
        user_id=1,
        outcome="placeholder",
        evidence=(
            DiagnosisEvidence(
                kind="confusion_pair",
                observation_ids=("obs-1", "obs-2"),
                weight=0.7,
                description=SECRET_ANSWER,
            ),
        ),
        confidence=0.6,
        rules_version=1,
        diagnosed_at=NOW,
    )
    event = diagnosis_produced_event(diagnosis)
    payload = as_loggable_dict(event)

    assert SECRET_ANSWER not in repr(payload)
    assert payload["evidence_count"] == 1
    assert "evidence" not in payload


def test_intervention_events_carry_no_free_text_rationale():
    plan = InterventionPlan(
        word_id=1, user_id=1, diagnosis_outcome="placeholder", strategy="contrast",
        policy_version=1, eligible=True, rationale=SECRET_ANSWER, planned_at=NOW,
    )
    payload = as_loggable_dict(intervention_scheduled_event(plan))
    assert SECRET_ANSWER not in repr(payload)
    assert "rationale" not in payload

    # `result` is a bounded status ("resolved"/"abandoned"/...), not free
    # text — unlike `rationale` above, it is intentionally kept in the
    # event, so this asserts it round-trips rather than that it's absent.
    outcome = InterventionOutcome(
        word_id=1, user_id=1, strategy="contrast", completed=True,
        result="resolved", recorded_at=NOW,
    )
    completed_payload = as_loggable_dict(intervention_completed_event(outcome))
    assert completed_payload["result"] == "resolved"


def test_diagnosis_corrected_event_only_carries_the_two_outcomes():
    before = Diagnosis(
        word_id=1, user_id=1, outcome="forgetting", evidence=(), confidence=0.5,
        rules_version=1, diagnosed_at=NOW,
    )
    after = Diagnosis(
        word_id=1, user_id=1, outcome="exact_confusion", evidence=(), confidence=0.7,
        rules_version=2, diagnosed_at=NOW,
    )
    payload = as_loggable_dict(diagnosis_corrected_event(before, after, corrected_at=NOW))
    assert payload["previous_outcome"] == "forgetting"
    assert payload["corrected_outcome"] == "exact_confusion"


def test_as_loggable_dict_refuses_a_payload_carrying_a_forbidden_field():
    # Guards the guard: if a future edit adds e.g. `term` to one of these
    # event types, this must fail loudly rather than silently log it.
    from dataclasses import dataclass

    @dataclass(frozen=True, slots=True)
    class _Unsafe:
        term: str

    import pytest

    with pytest.raises(ValueError):
        as_loggable_dict(_Unsafe(term="palabra"))


def test_the_forbidden_field_list_is_not_accidentally_empty():
    assert len(FORBIDDEN_FIELD_NAMES) >= 5
