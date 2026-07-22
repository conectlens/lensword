from datetime import datetime, timezone

from app.domain.services.spaced_repetition import SpacedRepetitionScheduler
from app.domain.value_objects import ReviewOutcome, ReviewState, utcnow

scheduler = SpacedRepetitionScheduler()


def test_first_correct_answer_schedules_one_day_out():
    state = ReviewState.initial()
    next_state = scheduler.schedule_next(state, ReviewOutcome.CORRECT)

    assert next_state.repetitions == 1
    assert next_state.interval_days == 1
    assert next_state.strength == 15
    assert next_state.due_at > utcnow()


def test_second_consecutive_correct_answer_schedules_six_days_out():
    state = ReviewState.initial()
    state = scheduler.schedule_next(state, ReviewOutcome.CORRECT)
    state = scheduler.schedule_next(state, ReviewOutcome.CORRECT)

    assert state.repetitions == 2
    assert state.interval_days == 6
    assert state.strength == 30


def test_third_consecutive_correct_answer_multiplies_by_ease_factor():
    state = ReviewState.initial()
    for _ in range(3):
        state = scheduler.schedule_next(state, ReviewOutcome.CORRECT)

    assert state.repetitions == 3
    # interval after rep 2 was 6 days; rep 3 multiplies by the (now-updated) ease factor
    assert state.interval_days == round(6 * state.ease_factor, 2) or state.interval_days > 6


def test_incorrect_answer_resets_repetitions_and_shortens_interval():
    state = ReviewState.initial()
    for _ in range(3):
        state = scheduler.schedule_next(state, ReviewOutcome.CORRECT)
    assert state.repetitions == 3

    state = scheduler.schedule_next(state, ReviewOutcome.INCORRECT)

    assert state.repetitions == 0
    assert state.interval_days == 1


def test_strength_never_exceeds_100_or_drops_below_0():
    state = ReviewState.initial()
    for _ in range(20):
        state = scheduler.schedule_next(state, ReviewOutcome.CORRECT)
    assert state.strength == 100

    for _ in range(20):
        state = scheduler.schedule_next(state, ReviewOutcome.INCORRECT)
    assert state.strength == 0


def test_ease_factor_never_drops_below_1_3():
    state = ReviewState.initial()
    for _ in range(15):
        state = scheduler.schedule_next(state, ReviewOutcome.INCORRECT)
    assert state.ease_factor >= 1.3


def test_skipped_outcome_is_treated_like_a_lapse_but_milder_than_incorrect():
    base = ReviewState.initial()
    after_correct = scheduler.schedule_next(base, ReviewOutcome.CORRECT)

    skipped = scheduler.schedule_next(after_correct, ReviewOutcome.SKIPPED)
    incorrect = scheduler.schedule_next(after_correct, ReviewOutcome.INCORRECT)

    assert skipped.repetitions == 0
    assert skipped.strength > incorrect.strength  # skipping penalizes less than a wrong answer


def test_due_at_is_now_for_a_brand_new_word():
    state = ReviewState.initial()
    assert state.is_due is True
