from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from app.domain.services.intervention_efficacy import (
    EfficacyContext,
    EfficacyStatus,
    InterventionObservation,
    estimate_efficacy,
)


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
CONTEXT = EfficacyContext("reversible_verbs", "es", "production", "medium", 7)


def _observation(index: int, *, control: bool, correct: bool, exposure: str | None = None):
    return InterventionObservation(
        evidence_id=f"evidence-{index}",
        learner_id=1,
        item_id=index,
        exposure_id=exposure or f"exposure-{index}",
        intervention_type="contrast",
        item_class=CONTEXT.item_class,
        language=CONTEXT.language,
        prompt_direction=CONTEXT.prompt_direction,
        difficulty=CONTEXT.difficulty,
        horizon_days=CONTEXT.horizon_days,
        correct=correct,
        is_control=control,
        observed_at=NOW + timedelta(days=index),
    )


def test_small_samples_abstain_without_a_modality_or_style_claim():
    estimate = estimate_efficacy(
        [_observation(1, control=False, correct=True)],
        intervention_type="contrast",
        context=CONTEXT,
    )
    assert estimate.status is EfficacyStatus.INSUFFICIENT_EVIDENCE
    assert estimate.recommendation is None
    assert estimate.effect is None


def test_delayed_control_comparison_reports_context_and_traceable_interval():
    observations = [
        *[_observation(index, control=False, correct=True) for index in range(1, 6)],
        *[_observation(index + 10, control=True, correct=False) for index in range(1, 6)],
    ]
    estimate = estimate_efficacy(observations, intervention_type="contrast", context=CONTEXT)
    assert estimate.status is EfficacyStatus.MEASURED
    assert estimate.effect == 1.0
    assert estimate.interval_low <= estimate.effect <= estimate.interval_high
    assert len(estimate.evidence_ids) == 10
    assert "7-day horizon" in estimate.recommendation
    assert "reversible_verbs" in estimate.recommendation


def test_repeated_immediate_exposure_is_not_counted_twice():
    duplicate = _observation(1, control=False, correct=True, exposure="same-plan")
    replacement = replace(
        duplicate,
        evidence_id="later-evidence",
        correct=False,
        observed_at=NOW + timedelta(days=2),
    )
    estimate = estimate_efficacy(
        [duplicate, replacement], intervention_type="contrast", context=CONTEXT, minimum_samples=2
    )
    assert estimate.intervention_samples == 1


def test_same_session_horizon_is_required():
    with pytest.raises(ValueError):
        replace(_observation(1, control=False, correct=True), horizon_days=0)
