from datetime import datetime, timezone

import pytest

from app.domain.services.companion_routines import (
    build_daily_check_in,
    build_micro_session_plan,
    build_recovery_routine,
    build_weekly_reflection,
)
from app.domain.services.intervention_efficacy import EfficacyContext, EfficacyEstimate, EfficacyStatus

CONTEXT = EfficacyContext("recall", "es", "l2_to_l1", "beginner", 3)


def test_daily_check_in_is_bounded_and_factual():
    zero = build_daily_check_in(0)
    assert zero.headline == "No words are due today."
    one = build_daily_check_in(1, goal_minutes=10)
    assert one.headline == "One word is due today."
    many = build_daily_check_in(4)
    assert many.headline == "4 words are due today."
    with pytest.raises(ValueError):
        build_daily_check_in(-1)


def _estimate(status, effect=None, samples=10):
    return EfficacyEstimate(
        intervention_type="mnemonic",
        context=CONTEXT,
        status=status,
        intervention_samples=samples,
        control_samples=samples,
        intervention_rate=0.7,
        control_rate=0.5,
        effect=effect,
        interval_low=None,
        interval_high=None,
        evidence_ids=("e1",),
        method="delayed_recall_control_comparison_v1",
    )


def test_weekly_reflection_never_states_an_effect_without_a_measured_sample():
    insufficient = _estimate(EfficacyStatus.INSUFFICIENT_EVIDENCE, effect=None)
    reflection = build_weekly_reflection([insufficient])
    assert reflection.measured == ()
    assert reflection.insufficient_evidence_count == 1
    assert "%" not in reflection.headline


def test_weekly_reflection_reports_sample_sizes_for_measured_interventions():
    measured = _estimate(EfficacyStatus.MEASURED, effect=0.15, samples=12)
    reflection = build_weekly_reflection([measured])
    assert reflection.measured == (measured,)
    assert "12 samples" in reflection.headline
    assert "+15.0%" in reflection.headline


def test_recovery_routine_uses_neutral_language_not_guilt_framing():
    recent = build_recovery_routine(2, due_count=3)
    assert "fallen behind" not in recent.headline.lower()
    assert "missed" not in recent.headline.lower()

    long_gap = build_recovery_routine(10, due_count=5)
    assert "fallen behind" not in long_gap.headline.lower()
    assert "missed" not in long_gap.headline.lower()
    assert "welcome back" in long_gap.headline.lower()
    assert long_gap.suggested_minutes == 5


def test_micro_session_plan_is_bounded_by_time_available():
    plan = build_micro_session_plan([1, 2, 3, 4, 5], minutes_available=3)
    assert plan.word_ids == (1, 2, 3)
    assert plan.estimated_minutes == 3
    with pytest.raises(ValueError):
        build_micro_session_plan([1], minutes_available=0)
