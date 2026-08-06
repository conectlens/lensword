"""Diagnosis-to-intervention planning (issue #185 TODO 0)."""
from __future__ import annotations

from datetime import datetime

from app.domain.services.diagnosis_contracts import (
    DIAGNOSIS_INSUFFICIENT_EVIDENCE,
    DIAGNOSIS_UNKNOWN,
    Diagnosis,
    DiagnosisEvidence,
)
from app.domain.services.diagnosis_engine import DiagnosisCategory
from app.domain.services.intervention_planning import (
    POLICY_VERSION,
    InterventionStrategy,
    plan_intervention,
)

BASE = datetime(2026, 8, 6, 9, 0)
WORD = 1
USER = 1


def _evidence() -> tuple[DiagnosisEvidence, ...]:
    return (DiagnosisEvidence(kind="test", observation_ids=("o1",), weight=0.8, description="d"),)


def _diagnosis(outcome: str, **overrides) -> Diagnosis:
    fields = dict(
        word_id=WORD, user_id=USER, outcome=outcome, evidence=_evidence(),
        confidence=0.8, rules_version=1, diagnosed_at=BASE, sample_size=3,
    )
    fields.update(overrides)
    return Diagnosis(**fields)


def test_an_abstention_produces_no_plan():
    assert plan_intervention(_diagnosis(DIAGNOSIS_UNKNOWN)) is None
    assert plan_intervention(_diagnosis(DIAGNOSIS_INSUFFICIENT_EVIDENCE)) is None


def test_an_unrecognised_outcome_string_produces_no_plan():
    """Defensive: an outcome that isn't even a DiagnosisCategory member
    (a future addition this module hasn't been updated for, or a bad
    fixture) must not crash the planner."""
    assert plan_intervention(_diagnosis("something_new")) is None


def test_every_real_diagnosis_category_maps_to_a_justified_strategy():
    """TODO 0's own verify clause, positive half: every diagnosed category
    (not an abstention) produces a plan with a stated rationale."""
    for category in DiagnosisCategory:
        if category.value in (DIAGNOSIS_UNKNOWN, DIAGNOSIS_INSUFFICIENT_EVIDENCE):
            continue
        plan = plan_intervention(_diagnosis(category.value))
        assert plan is not None, f"{category} produced no plan"
        assert plan.eligible is True
        assert plan.rationale
        assert plan.strategy in {s.value for s in InterventionStrategy}


def test_exact_confusion_maps_to_contrast():
    plan = plan_intervention(_diagnosis(DiagnosisCategory.EXACT_CONFUSION.value))
    assert plan.strategy == InterventionStrategy.CONTRAST.value


def test_missing_prerequisite_maps_to_prerequisite_path():
    plan = plan_intervention(_diagnosis(DiagnosisCategory.MISSING_PREREQUISITE.value))
    assert plan.strategy == InterventionStrategy.PREREQUISITE_PATH.value


def test_forgetting_and_weak_acquisition_both_map_to_acquisition_restart():
    forgetting = plan_intervention(_diagnosis(DiagnosisCategory.FORGETTING.value))
    weak = plan_intervention(_diagnosis(DiagnosisCategory.WEAK_ACQUISITION.value))
    assert forgetting.strategy == InterventionStrategy.ACQUISITION_RESTART.value
    assert weak.strategy == InterventionStrategy.ACQUISITION_RESTART.value


def test_spatial_anchor_is_never_auto_selected():
    """User-invoked, not diagnosis-triggered — no category maps to it."""
    for category in DiagnosisCategory:
        plan = plan_intervention(_diagnosis(category.value))
        if plan is not None:
            assert plan.strategy != InterventionStrategy.SPATIAL_ANCHOR.value


def test_a_plan_carries_the_diagnosis_it_was_made_from():
    diagnosis = _diagnosis(DiagnosisCategory.EXACT_CONFUSION.value, word_id=42, user_id=7)

    plan = plan_intervention(diagnosis)

    assert plan.word_id == 42
    assert plan.user_id == 7
    assert plan.diagnosis_outcome == DiagnosisCategory.EXACT_CONFUSION.value
    assert plan.policy_version == POLICY_VERSION
