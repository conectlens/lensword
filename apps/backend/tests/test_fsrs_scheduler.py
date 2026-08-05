import math
import random
from dataclasses import replace

import pytest

from app.domain.services.spaced_repetition import (
    FSRSScheduler,
    SpacedRepetitionScheduler,
    _MAX_INTERVAL_DAYS,
)
from app.domain.value_objects import ReviewOutcome, ReviewState


def test_fsrs_schedules_and_reports_retrievability():
    scheduler = FSRSScheduler()
    initial = ReviewState.initial()
    scheduled = scheduler.schedule_next(initial, ReviewOutcome.CORRECT)
    assert scheduled.repetitions == 1
    assert scheduled.interval_days > 0
    assert 0 < scheduler.retrievability(scheduled) <= 1


def test_ten_consecutive_correct_reviews_strictly_increase_and_reach_thirty_days():
    """Guards the bug (issue #173): re-deriving stability from the previous,
    already-clamped interval pinned every FSRS word at a 1.00-day interval
    forever. Persisted stability must compound instead."""
    scheduler = FSRSScheduler()
    state = ReviewState.initial()
    intervals = []
    for _ in range(10):
        state = scheduler.schedule_next(state, ReviewOutcome.CORRECT)
        intervals.append(state.interval_days)

    assert intervals == sorted(intervals)
    assert len(set(intervals)) == len(intervals)  # strictly increasing, not just non-decreasing
    assert intervals[-1] >= 30


def test_retrievability_matches_the_scheduler_own_promise_at_the_scheduled_moment():
    """This test fails on `main` today: retrievability() divided elapsed time
    by interval_days, but interval_days is ~0.105x of stability, so it
    reported R=0.368 at the exact moment the scheduler believed R=0.9."""
    from datetime import timedelta

    scheduler = FSRSScheduler()
    state = scheduler.schedule_next(ReviewState.initial(), ReviewOutcome.CORRECT)

    # last_reviewed_at is "now" in schedule_next, so backdating it by exactly
    # interval_days simulates checking in right when the word came due.
    backdated = replace(state, last_reviewed_at=state.last_reviewed_at - timedelta(days=state.interval_days))

    assert scheduler.retrievability(backdated) == pytest.approx(0.9, abs=0.01)


@pytest.mark.parametrize("scheduler", [SpacedRepetitionScheduler(), FSRSScheduler()])
def test_scheduler_invariants_hold_over_a_hundred_random_reviews(scheduler):
    """Property test (issue #173 TODO 3), without adding a hypothesis
    dependency: a fixed seed drives many outcome sequences, and every step
    must hold three invariants regardless of the sequence drawn."""
    rng = random.Random(20260805)
    outcomes = [ReviewOutcome.CORRECT, ReviewOutcome.INCORRECT, ReviewOutcome.SKIPPED]

    for _run in range(20):
        # The very first review has no real "previous interval" to compare
        # against — ReviewState.initial()'s interval_days=0 is a sentinel for
        # "never reviewed," not a scheduled interval an outcome could grow or
        # shrink. Seed one review outside the invariant checks, then verify
        # the remaining 99 transitions in this run of 100.
        state = scheduler.schedule_next(ReviewState.initial(), rng.choice(outcomes))
        previous_interval = state.interval_days

        for _step in range(99):
            outcome = rng.choice(outcomes)
            next_state = scheduler.schedule_next(state, outcome)

            assert math.isfinite(next_state.interval_days)
            assert not math.isnan(next_state.interval_days)
            assert next_state.interval_days <= _MAX_INTERVAL_DAYS

            if outcome == ReviewOutcome.CORRECT:
                assert next_state.interval_days >= previous_interval
            elif outcome == ReviewOutcome.INCORRECT:
                assert next_state.interval_days <= previous_interval

            previous_interval = next_state.interval_days
            state = next_state
