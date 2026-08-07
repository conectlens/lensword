from datetime import datetime, timedelta, timezone

import pytest

from app.domain.services.intervention_efficacy import EfficacyStatus, InterventionObservation
from app.domain.services.longitudinal_evaluation import (
    MINIMUM_ADAPTATION_EFFECT,
    compare_cohorts,
)

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _cohort_observation(index: int, *, correct: bool, cohort: str) -> InterventionObservation:
    return InterventionObservation(
        evidence_id=f"{cohort}-evidence-{index}",
        learner_id=index,  # a distinct learner per row, like a real cohort
        item_id=index,
        exposure_id=f"{cohort}-exposure-{index}",
        intervention_type="adaptive_policy",
        item_class="general",
        language="es",
        prompt_direction="production",
        difficulty="medium",
        modality="text",
        horizon_days=7,
        correct=correct,
        is_control=(cohort == "control"),
        observed_at=NOW + timedelta(days=index),
    )


def _cohort(n: int, *, correct_count: int, cohort: str) -> list[InterventionObservation]:
    return [
        _cohort_observation(i, correct=i < correct_count, cohort=cohort) for i in range(n)
    ]


def test_small_cohorts_abstain():
    adaptive = _cohort(5, correct_count=5, cohort="adaptive")
    control = _cohort(5, correct_count=0, cohort="control")
    result = compare_cohorts(adaptive, control, minimum_samples=30)
    assert result.status is EfficacyStatus.INSUFFICIENT_EVIDENCE
    assert result.adaptation_recommended is False
    assert result.effect is None


def test_a_strong_and_consistent_effect_recommends_adaptation():
    adaptive = _cohort(60, correct_count=54, cohort="adaptive")  # 90%
    control = _cohort(60, correct_count=24, cohort="control")  # 40%
    result = compare_cohorts(adaptive, control, minimum_samples=30)
    assert result.status is EfficacyStatus.MEASURED
    assert result.effect == pytest.approx(0.5, abs=0.01)
    assert result.interval_low >= MINIMUM_ADAPTATION_EFFECT
    assert result.adaptation_recommended is True


def test_a_weak_effect_does_not_recommend_adaptation():
    """Even with enough samples, an effect whose interval does not clear the
    minimum threshold must not gate automatic adaptation on (#186's success
    metric: 'automatic adaptation only above predefined evidence
    thresholds')."""
    adaptive = _cohort(60, correct_count=32, cohort="adaptive")  # ~53%
    control = _cohort(60, correct_count=30, cohort="control")  # 50%
    result = compare_cohorts(adaptive, control, minimum_samples=30)
    assert result.status is EfficacyStatus.MEASURED
    assert result.adaptation_recommended is False


def test_no_fabricated_outperformance_when_cohorts_are_equal():
    adaptive = _cohort(40, correct_count=20, cohort="adaptive")
    control = _cohort(40, correct_count=20, cohort="control")
    result = compare_cohorts(adaptive, control, minimum_samples=30)
    assert result.status is EfficacyStatus.MEASURED
    assert result.effect == pytest.approx(0.0, abs=0.01)
    assert result.adaptation_recommended is False


def test_repeated_immediate_exposure_within_a_cohort_is_not_double_counted():
    from dataclasses import replace

    base = _cohort_observation(0, correct=True, cohort="adaptive")
    duplicate = replace(base, evidence_id="later", correct=False, observed_at=NOW + timedelta(hours=1))
    result = compare_cohorts(
        [base, duplicate], _cohort(2, correct_count=1, cohort="control"), minimum_samples=2
    )
    assert result.adaptive_samples == 1


def test_minimum_samples_must_be_at_least_two():
    with pytest.raises(ValueError):
        compare_cohorts([], [], minimum_samples=1)
