"""AI Learning Diagnosis domain contracts (#180, ADR 0007, issue #181 TODO 2).

Pure unit tests, no application or infrastructure dependencies: these
contracts have no engine behind them yet (that's #183/#184), so what's
tested here is that every contract can be constructed and evaluated on its
own, and that the invariants stated in its docstring actually hold.
"""
from __future__ import annotations

from datetime import datetime

import pytest

from app.domain.services.diagnosis_contracts import (
    DIAGNOSIS_INSUFFICIENT_EVIDENCE,
    DIAGNOSIS_UNKNOWN,
    AcquisitionState,
    Diagnosis,
    DiagnosisEvidence,
    InterventionOutcome,
    InterventionPlan,
    LearningObservation,
)
from app.domain.value_objects import ReviewOutcome, SessionMode

NOW = datetime(2026, 8, 6, 9, 0)


def test_a_learning_observation_is_valid_with_only_the_legacy_fields():
    # #182 TODO 0: old clients that only ever submit correct/incorrect must
    # remain valid — every richer field is optional.
    obs = LearningObservation(
        observation_id="obs-1",
        word_id=1,
        user_id=1,
        outcome=ReviewOutcome.CORRECT,
        session_mode=SessionMode.STANDARD,
        observed_at=NOW,
    )
    assert obs.attempted_answer is None
    assert obs.response_time_ms is None
    assert obs.self_reported_confidence is None
    assert obs.schema_version == 1


def test_a_learning_observation_carries_the_richer_context_when_supplied():
    obs = LearningObservation(
        observation_id="obs-2",
        word_id=1,
        user_id=1,
        outcome=ReviewOutcome.INCORRECT,
        session_mode=SessionMode.FOCUS,
        observed_at=NOW,
        attempted_answer="prestar",
        response_time_ms=4200,
        prompt_direction="translation_to_term",
        hint_used=True,
        self_reported_confidence=0.4,
    )
    assert obs.attempted_answer == "prestar"
    assert obs.prompt_direction == "translation_to_term"
    assert obs.self_reported_confidence == 0.4


def test_diagnosis_evidence_rejects_a_weight_outside_zero_to_one():
    with pytest.raises(ValueError):
        DiagnosisEvidence(kind="confusion_pair", observation_ids=("obs-1",), weight=1.5, description="x")


def test_diagnosis_evidence_rejects_citing_nothing():
    with pytest.raises(ValueError):
        DiagnosisEvidence(kind="confusion_pair", observation_ids=(), weight=0.5, description="x")


def _evidence(weight: float = 0.6) -> DiagnosisEvidence:
    return DiagnosisEvidence(
        kind="confusion_pair", observation_ids=("obs-1", "obs-2"), weight=weight, description="x"
    )


def test_diagnosis_rejects_a_confidence_outside_zero_to_one():
    with pytest.raises(ValueError):
        Diagnosis(
            word_id=1,
            user_id=1,
            outcome=DIAGNOSIS_UNKNOWN,
            evidence=(),
            confidence=1.2,
            rules_version=1,
            diagnosed_at=NOW,
        )


def test_diagnosis_confidence_may_be_absent_for_an_abstention():
    # Not every diagnosis has a confidence to report — an abstention has
    # none by construction, and this must not be forced to a fabricated 0.0.
    diagnosis = Diagnosis(
        word_id=1,
        user_id=1,
        outcome=DIAGNOSIS_INSUFFICIENT_EVIDENCE,
        evidence=(),
        confidence=None,
        rules_version=1,
        diagnosed_at=NOW,
    )
    assert diagnosis.confidence is None


@pytest.mark.parametrize("outcome", [DIAGNOSIS_UNKNOWN, DIAGNOSIS_INSUFFICIENT_EVIDENCE])
def test_the_two_abstention_outcomes_report_as_abstentions(outcome):
    diagnosis = Diagnosis(
        word_id=1, user_id=1, outcome=outcome, evidence=(), confidence=None,
        rules_version=1, diagnosed_at=NOW,
    )
    assert diagnosis.is_abstention is True


def test_a_diagnosis_with_a_real_cause_is_not_an_abstention():
    # #183 has not shipped its closed taxonomy yet, so this uses a
    # placeholder outcome string — the point is only that abstention
    # detection is by membership in the two known sentinels, not by
    # "outcome is falsy" or some other accidental proxy.
    diagnosis = Diagnosis(
        word_id=1, user_id=1, outcome="placeholder_real_cause", evidence=(_evidence(),),
        confidence=0.8, rules_version=1, diagnosed_at=NOW,
    )
    assert diagnosis.is_abstention is False


def test_an_intervention_plan_can_be_ineligible_with_a_stated_reason():
    # #185 TODO 0: "unsupported cases return no intervention" — this
    # contract represents that as an explicit ineligible plan with a
    # rationale, not the absence of a plan, so the reason is recorded.
    plan = InterventionPlan(
        word_id=1, user_id=1, diagnosis_outcome=DIAGNOSIS_INSUFFICIENT_EVIDENCE,
        strategy="isolate", policy_version=1, eligible=False,
        rationale="not enough evidence to select a strategy", planned_at=NOW,
    )
    assert plan.eligible is False
    assert plan.scheduled_for is None


def test_an_intervention_outcome_can_record_a_plan_that_never_ran():
    outcome = InterventionOutcome(
        word_id=1, user_id=1, strategy="contrast", completed=False,
        result="abandoned", recorded_at=NOW,
    )
    assert outcome.completed is False
    assert outcome.completed_at is None


def test_acquisition_state_defaults_to_not_graduated():
    state = AcquisitionState(
        word_id=1, user_id=1, rung=0, ladder_version=1, started_at=NOW, updated_at=NOW,
    )
    assert state.graduated is False
