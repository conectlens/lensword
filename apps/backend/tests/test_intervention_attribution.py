from datetime import datetime, timedelta, timezone

from app.domain.services.diagnosis_contracts import InterventionPlan, LearningObservation
from app.domain.services.intervention_attribution import (
    WordEfficacyContext,
    attribute_efficacy_observations,
)
from app.domain.value_objects import ReviewOutcome, SessionMode

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
WORD_CREATED = NOW - timedelta(days=60)


def _observation(
    obs_id: str,
    *,
    word_id: int,
    observed_at: datetime,
    correct: bool,
    plan_ref: str | None = None,
    modality: str | None = "text",
    prompt_direction: str | None = "production",
) -> LearningObservation:
    return LearningObservation(
        observation_id=obs_id,
        word_id=word_id,
        user_id=1,
        outcome=ReviewOutcome.CORRECT if correct else ReviewOutcome.INCORRECT,
        session_mode=SessionMode.STANDARD,
        observed_at=observed_at,
        intervention_plan_ref=plan_ref,
        modality=modality,
        prompt_direction=prompt_direction,
    )


def _plan(word_id: int, strategy: str, planned_at: datetime) -> InterventionPlan:
    return InterventionPlan(
        word_id=word_id,
        user_id=1,
        diagnosis_outcome="exact_confusion",
        strategy=strategy,
        policy_version=2,
        eligible=True,
        rationale="test",
        planned_at=planned_at,
    )


CONTEXT = {
    1: WordEfficacyContext(item_class="verb", language="Spanish", difficulty="B1", created_at=WORD_CREATED)
}


def test_word_with_no_plans_contributes_no_observations():
    observations = [_observation("o1", word_id=1, observed_at=NOW, correct=True)]
    result = attribute_efficacy_observations(
        learner_id=1, observations=observations, plans=[], word_contexts=CONTEXT
    )
    assert result == []


def test_plan_linked_observation_is_intervention_arm_for_its_strategy():
    plan_time = NOW - timedelta(days=8)
    observations = [
        _observation("o1", word_id=1, observed_at=plan_time + timedelta(days=1), correct=True, plan_ref="p1")
    ]
    result = attribute_efficacy_observations(
        learner_id=1,
        observations=observations,
        plans=[_plan(1, "contrast", plan_time)],
        word_contexts=CONTEXT,
    )
    assert len(result) == 1
    row = result[0]
    assert row.is_control is False
    assert row.intervention_type == "contrast"
    assert row.correct is True
    assert row.item_class == "verb"
    assert row.language == "Spanish"


def test_organic_observation_is_control_arm_for_every_strategy_this_word_has_tried():
    plan_time = NOW - timedelta(days=10)
    observations = [
        # organic — no plan_ref
        _observation("o1", word_id=1, observed_at=NOW, correct=False),
    ]
    result = attribute_efficacy_observations(
        learner_id=1,
        observations=observations,
        plans=[_plan(1, "contrast", plan_time), _plan(1, "isolate", plan_time)],
        word_contexts=CONTEXT,
    )
    strategies = {row.intervention_type for row in result}
    assert strategies == {"contrast", "isolate"}
    assert all(row.is_control for row in result)


def test_horizon_is_bucketed_to_the_nearest_canonical_value():
    plan_time = NOW - timedelta(days=9)
    observations = [
        # ~7 days after the plan started -> bucket 7
        _observation("o1", word_id=1, observed_at=plan_time + timedelta(days=6), correct=True, plan_ref="p1"),
        # ~24 days after -> nearest canonical bucket is 30
        _observation("o2", word_id=1, observed_at=plan_time + timedelta(days=24), correct=True, plan_ref="p1"),
    ]
    result = attribute_efficacy_observations(
        learner_id=1,
        observations=observations,
        plans=[_plan(1, "contrast", plan_time)],
        word_contexts=CONTEXT,
    )
    horizons = sorted(row.horizon_days for row in result)
    assert horizons == [7, 30]


def test_exposure_count_and_prior_mastery_evolve_across_observations():
    plan_time = NOW - timedelta(days=20)
    observations = [
        _observation("o1", word_id=1, observed_at=plan_time - timedelta(days=10), correct=True),
        _observation("o2", word_id=1, observed_at=plan_time - timedelta(days=9), correct=True),
        _observation("o3", word_id=1, observed_at=plan_time + timedelta(days=1), correct=True, plan_ref="p1"),
    ]
    result = attribute_efficacy_observations(
        learner_id=1,
        observations=observations,
        plans=[_plan(1, "contrast", plan_time)],
        word_contexts=CONTEXT,
    )
    by_evidence = {row.evidence_id: row for row in result}
    # o1: first ever exposure -> "new" mastery, exposure_count 1
    assert by_evidence["o1"].prior_mastery == "new"
    assert by_evidence["o1"].exposure_count == 1
    # o2: one prior correct exposure -> "strong"
    assert by_evidence["o2"].prior_mastery == "strong"
    assert by_evidence["o2"].exposure_count == 2
    # o3 (the plan-linked one): two prior correct exposures -> "strong"
    assert by_evidence["o3"].prior_mastery == "strong"
    assert by_evidence["o3"].exposure_count == 3


def test_same_day_observations_share_an_exposure_id():
    plan_time = NOW - timedelta(days=8)
    day = plan_time + timedelta(days=1)
    observations = [
        _observation("o1", word_id=1, observed_at=day, correct=True, plan_ref="p1"),
        _observation("o2", word_id=1, observed_at=day + timedelta(hours=2), correct=False, plan_ref="p1"),
    ]
    result = attribute_efficacy_observations(
        learner_id=1,
        observations=observations,
        plans=[_plan(1, "contrast", plan_time)],
        word_contexts=CONTEXT,
    )
    exposure_ids = {row.exposure_id for row in result}
    assert len(exposure_ids) == 1


def test_word_with_no_context_is_skipped():
    observations = [_observation("o1", word_id=99, observed_at=NOW, correct=True, plan_ref="p1")]
    result = attribute_efficacy_observations(
        learner_id=1,
        observations=observations,
        plans=[_plan(99, "contrast", NOW - timedelta(days=1))],
        word_contexts=CONTEXT,  # only has word 1
    )
    assert result == []
