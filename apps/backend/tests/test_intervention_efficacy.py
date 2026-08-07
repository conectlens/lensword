from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from app.domain.services.diagnosis_contracts import ModalityPreference
from app.domain.services.intervention_efficacy import (
    DEFAULT_MAX_AGE_DAYS,
    EfficacyContext,
    EfficacyStatus,
    InterventionObservation,
    build_modality_insight,
    estimate_efficacy,
    refresh_staleness,
)


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
LEARNER = 1
CONTEXT = EfficacyContext(LEARNER, "reversible_verbs", "es", "production", "medium", "text", 7)


def _observation(
    index: int,
    *,
    control: bool,
    correct: bool,
    exposure: str | None = None,
    learner_id: int = LEARNER,
    context: EfficacyContext = CONTEXT,
    intervention_type: str = "contrast",
    prior_mastery: str = "weak",
    exposure_count: int = 1,
):
    return InterventionObservation(
        evidence_id=f"evidence-{learner_id}-{intervention_type}-{index}",
        learner_id=learner_id,
        item_id=index,
        exposure_id=exposure or f"exposure-{learner_id}-{index}",
        intervention_type=intervention_type,
        item_class=context.item_class,
        language=context.language,
        prompt_direction=context.prompt_direction,
        difficulty=context.difficulty,
        modality=context.modality,
        horizon_days=context.horizon_days,
        correct=correct,
        is_control=control,
        observed_at=NOW + timedelta(days=index),
        prior_mastery=prior_mastery,
        exposure_count=exposure_count,
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
    # TODO 2: the recommendation carries its own period, not just an effect.
    assert "between" in estimate.recommendation
    assert "intervention and" in estimate.recommendation


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


# --- TODO 0: per-learner + modality axes -----------------------------------


def test_two_learners_are_never_pooled_into_one_estimate():
    """#186 TODO 0's "model performance by learner": a strong effect for
    learner 1 must not leak into learner 2's context, and vice versa."""
    learner_1 = [
        *[_observation(index, control=False, correct=True, learner_id=1) for index in range(1, 6)],
        *[_observation(index + 10, control=True, correct=False, learner_id=1) for index in range(1, 6)],
    ]
    # Learner 2 has almost no evidence at all.
    learner_2 = [_observation(1, control=False, correct=True, learner_id=2)]

    estimate_1 = estimate_efficacy(
        learner_1 + learner_2, intervention_type="contrast", context=CONTEXT
    )
    estimate_2 = estimate_efficacy(
        learner_1 + learner_2,
        intervention_type="contrast",
        context=replace(CONTEXT, learner_id=2),
    )
    assert estimate_1.status is EfficacyStatus.MEASURED
    assert estimate_2.status is EfficacyStatus.INSUFFICIENT_EVIDENCE


def test_modality_is_a_distinct_axis_from_item_class():
    """Same learner/item_class/horizon, different modality: these must not
    be merged into a single comparison — a modality claim and a technique
    claim are different, independently falsifiable statements (TODO 0)."""
    image_context = replace(CONTEXT, modality="image")
    text_observations = [
        *[_observation(index, control=False, correct=True) for index in range(1, 6)],
        *[_observation(index + 10, control=True, correct=False) for index in range(1, 6)],
    ]
    image_observations = [
        _observation(index + 100, control=False, correct=True, context=image_context) for index in range(1, 3)
    ]
    estimate_text = estimate_efficacy(
        text_observations + image_observations, intervention_type="contrast", context=CONTEXT
    )
    estimate_image = estimate_efficacy(
        text_observations + image_observations, intervention_type="contrast", context=image_context
    )
    assert estimate_text.status is EfficacyStatus.MEASURED
    assert estimate_image.status is EfficacyStatus.INSUFFICIENT_EVIDENCE
    assert estimate_image.intervention_samples == 2


# --- TODO 1: confounding detection ------------------------------------------


def test_confounded_exposure_counts_produce_inconclusive_not_a_false_effect():
    """Synthetic confounding fixture (#186 TODO 1's verify clause): the
    intervention arm is all first-time exposures (a fresh, easy win) and the
    control arm is all tenth-plus exposures of already-struggled items. A
    naive comparison would read this as the intervention working; the
    confounding check must abstain instead."""
    intervention = [
        _observation(index, control=False, correct=True, exposure_count=1, prior_mastery="new")
        for index in range(1, 6)
    ]
    control = [
        _observation(index + 10, control=True, correct=False, exposure_count=8, prior_mastery="weak")
        for index in range(1, 6)
    ]
    estimate = estimate_efficacy(intervention + control, intervention_type="contrast", context=CONTEXT)
    assert estimate.status is EfficacyStatus.INCONCLUSIVE
    assert estimate.effect is None
    assert "prior mastery" in estimate.reason or "exposure" in estimate.reason


def test_confounded_prior_mastery_distribution_produces_inconclusive():
    intervention = [
        _observation(index, control=False, correct=True, prior_mastery="strong", exposure_count=3)
        for index in range(1, 6)
    ]
    control = [
        _observation(index + 10, control=True, correct=False, prior_mastery="new", exposure_count=3)
        for index in range(1, 6)
    ]
    estimate = estimate_efficacy(intervention + control, intervention_type="contrast", context=CONTEXT)
    assert estimate.status is EfficacyStatus.INCONCLUSIVE


def test_balanced_arms_are_not_flagged_as_confounded():
    """The confounding check must not fire on ordinary, comparable data —
    otherwise every real comparison would abstain."""
    intervention = [
        _observation(index, control=False, correct=True, prior_mastery="weak", exposure_count=2)
        for index in range(1, 6)
    ]
    control = [
        _observation(index + 10, control=True, correct=False, prior_mastery="weak", exposure_count=2)
        for index in range(1, 6)
    ]
    estimate = estimate_efficacy(intervention + control, intervention_type="contrast", context=CONTEXT)
    assert estimate.status is EfficacyStatus.MEASURED


# --- TODO 2: staleness / expiry ---------------------------------------------


def test_measured_estimate_gets_a_validity_window():
    observations = [
        *[_observation(index, control=False, correct=True) for index in range(1, 6)],
        *[_observation(index + 10, control=True, correct=False) for index in range(1, 6)],
    ]
    estimate = estimate_efficacy(observations, intervention_type="contrast", context=CONTEXT)
    assert estimate.valid_until == estimate.period_end + timedelta(days=DEFAULT_MAX_AGE_DAYS)


def test_stale_estimate_is_downgraded_to_insufficient_evidence():
    observations = [
        *[_observation(index, control=False, correct=True) for index in range(1, 6)],
        *[_observation(index + 10, control=True, correct=False) for index in range(1, 6)],
    ]
    estimate = estimate_efficacy(observations, intervention_type="contrast", context=CONTEXT)
    long_after = estimate.valid_until + timedelta(days=1)
    refreshed = refresh_staleness(estimate, now=long_after)
    assert refreshed.status is EfficacyStatus.INSUFFICIENT_EVIDENCE
    assert refreshed.effect is None
    assert refreshed.recommendation is None


def test_fresh_estimate_is_not_downgraded():
    observations = [
        *[_observation(index, control=False, correct=True) for index in range(1, 6)],
        *[_observation(index + 10, control=True, correct=False) for index in range(1, 6)],
    ]
    estimate = estimate_efficacy(observations, intervention_type="contrast", context=CONTEXT)
    still_fresh = refresh_staleness(estimate, now=estimate.period_end + timedelta(days=1))
    assert still_fresh.status is EfficacyStatus.MEASURED
    assert still_fresh.effect == estimate.effect


# --- TODO 0: preference kept separate from measured effectiveness ----------


def test_stated_preference_never_becomes_a_measured_effectiveness_claim():
    """A learner who says "I like images" must not have that statement
    reported back as evidence images work — `build_modality_insight` keeps
    the two in separate fields even when the measured estimate for that
    exact modality is a flat/no-evidence result."""
    preference = ModalityPreference(user_id=LEARNER, modality="image", stated_at=NOW)
    image_context = replace(CONTEXT, modality="image")
    no_evidence = estimate_efficacy(
        [_observation(1, control=False, correct=True, context=image_context)],
        intervention_type="contrast",
        context=image_context,
    )
    insight = build_modality_insight("image", preference, [no_evidence])
    assert insight.stated_preference is True
    assert all(e.status is EfficacyStatus.INSUFFICIENT_EVIDENCE for e in insight.measured_estimates)
    # The preference field says the learner likes it; nothing here upgrades
    # that into an effectiveness claim on its own.
    assert insight.measured_estimates[0].recommendation is None


def test_no_stated_preference_is_distinct_from_a_negative_one():
    insight = build_modality_insight("image", None, [])
    assert insight.stated_preference is False
    assert insight.measured_estimates == ()


def test_refresh_staleness_is_a_no_op_on_insufficient_evidence():
    estimate = estimate_efficacy(
        [_observation(1, control=False, correct=True)],
        intervention_type="contrast",
        context=CONTEXT,
    )
    refreshed = refresh_staleness(estimate, now=NOW + timedelta(days=9999))
    assert refreshed.status is EfficacyStatus.INSUFFICIENT_EVIDENCE
    assert refreshed == estimate
