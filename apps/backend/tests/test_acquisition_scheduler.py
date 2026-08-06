"""The graduated acquisition loop's pure domain logic (#180, issue #184).

Covers TODO 0's verify step (one acquisition sequence produces one bounded
FSRS handoff, not interval inflation from every micro-recall), TODO 1's
(every transition deterministic under a fake clock), and TODO 4's routing
decision (forgetting/new-item/confusion choose different paths).
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.domain.services.acquisition import (
    LADDER_OFFSETS,
    LADDER_POLICY_VERSION,
    AcquisitionEntryReason,
    AcquisitionScheduler,
    graduate,
    should_enter_acquisition,
)
from app.domain.services.diagnosis_contracts import Diagnosis
from app.domain.services.spaced_repetition import FSRSScheduler
from app.domain.value_objects import ReviewOutcome, ReviewState

NOW = datetime(2026, 8, 6, 9, 0)


def _diagnosis(outcome: str) -> Diagnosis:
    return Diagnosis(
        word_id=1, user_id=1, outcome=outcome, evidence=(), confidence=0.6,
        rules_version=1, diagnosed_at=NOW,
    )


def _review_state() -> ReviewState:
    return ReviewState(
        strength=50, ease_factor=2.5, interval_days=1, repetitions=0,
        due_at=NOW, last_reviewed_at=None, stability=None,
    )


# --- Routing (TODO 4) ---


def test_explicit_choice_always_wins():
    reason = should_enter_acquisition(
        is_new_word=False, diagnosis=_diagnosis("exact_confusion"), explicit_choice=True
    )
    assert reason is AcquisitionEntryReason.EXPLICIT_USER_CHOICE


def test_weak_acquisition_diagnosis_enters_the_loop():
    reason = should_enter_acquisition(is_new_word=False, diagnosis=_diagnosis("weak_acquisition"))
    assert reason is AcquisitionEntryReason.WEAK_ACQUISITION_DIAGNOSIS


def test_a_new_word_with_no_diagnosis_enters_as_a_new_item():
    reason = should_enter_acquisition(is_new_word=True, diagnosis=None)
    assert reason is AcquisitionEntryReason.NEW_ITEM


def test_ordinary_forgetting_does_not_enter_the_loop():
    """Forgetting after demonstrated recall is FSRS's problem, not a
    same-day re-acquisition problem — the two-horizon split TODO 0 draws."""
    reason = should_enter_acquisition(is_new_word=False, diagnosis=_diagnosis("forgetting"))
    assert reason is None


def test_exact_confusion_does_not_enter_the_loop():
    """TODO 4: confusion is explicitly routed elsewhere (#185's contrast
    intervention), not rehearsed here as if it were a solitary weak item."""
    reason = should_enter_acquisition(is_new_word=False, diagnosis=_diagnosis("exact_confusion"))
    assert reason is None


def test_no_evidence_at_all_does_not_enter_the_loop():
    reason = should_enter_acquisition(is_new_word=False, diagnosis=None)
    assert reason is None


# --- Ladder transitions (TODO 1) ---


def test_start_places_the_ladder_at_rung_zero():
    state = AcquisitionScheduler().start(word_id=1, user_id=1, now=NOW)
    assert state.rung == 0
    assert state.ladder_version == LADDER_POLICY_VERSION
    assert state.graduated is False
    assert state.started_at == state.updated_at == NOW


def test_due_at_is_the_first_offset_from_the_start():
    scheduler = AcquisitionScheduler()
    state = scheduler.start(word_id=1, user_id=1, now=NOW)
    assert scheduler.due_at(state) == NOW + LADDER_OFFSETS[1][0]


def test_a_correct_answer_advances_one_rung_and_moves_due_at_forward():
    scheduler = AcquisitionScheduler()
    state = scheduler.start(word_id=1, user_id=1, now=NOW)
    later = NOW + timedelta(seconds=30)

    state = scheduler.advance(state, ReviewOutcome.CORRECT, later)

    assert state.rung == 1
    assert state.graduated is False
    assert scheduler.due_at(state) == later + LADDER_OFFSETS[1][1]


def test_an_incorrect_answer_backs_off_but_never_below_rung_zero():
    scheduler = AcquisitionScheduler()
    state = scheduler.start(word_id=1, user_id=1, now=NOW)
    state = scheduler.advance(state, ReviewOutcome.INCORRECT, NOW + timedelta(minutes=1))
    assert state.rung == 0

    # Climb up first so a later failure has somewhere to back off from.
    for _ in range(3):
        state = scheduler.advance(state, ReviewOutcome.CORRECT, state.updated_at + timedelta(minutes=1))
    assert state.rung == 3

    state = scheduler.advance(state, ReviewOutcome.INCORRECT, state.updated_at + timedelta(minutes=1))
    assert state.rung == 1  # backed off by 2, floored at 0


def test_completing_every_rung_quickly_does_not_graduate():
    """The gap requirement, not just rung count — a ladder finished in
    seconds has not demonstrated delayed recall."""
    scheduler = AcquisitionScheduler()
    state = scheduler.start(word_id=1, user_id=1, now=NOW)
    t = NOW
    for _ in range(len(LADDER_OFFSETS[1])):
        t += timedelta(seconds=1)
        state = scheduler.advance(state, ReviewOutcome.CORRECT, t)

    assert state.graduated is False
    # Parked one below the ladder's end rather than demanding it loop
    # forever — the next correct answer, once the gap has passed, graduates it.
    assert state.rung == len(LADDER_OFFSETS[1]) - 1


def test_completing_every_rung_with_a_real_gap_graduates():
    scheduler = AcquisitionScheduler()
    state = scheduler.start(word_id=1, user_id=1, now=NOW)
    t = NOW
    for _ in range(len(LADDER_OFFSETS[1])):
        t += timedelta(hours=1)
        state = scheduler.advance(state, ReviewOutcome.CORRECT, t)

    assert state.graduated is True


def test_a_graduated_ladder_does_not_advance_further():
    scheduler = AcquisitionScheduler()
    state = scheduler.start(word_id=1, user_id=1, now=NOW)
    t = NOW
    for _ in range(len(LADDER_OFFSETS[1])):
        t += timedelta(hours=1)
        state = scheduler.advance(state, ReviewOutcome.CORRECT, t)
    assert state.graduated is True

    unchanged = scheduler.advance(state, ReviewOutcome.INCORRECT, t + timedelta(minutes=1))
    assert unchanged == state


def test_pause_freezes_the_rung_and_moves_updated_at_forward():
    scheduler = AcquisitionScheduler()
    state = scheduler.start(word_id=1, user_id=1, now=NOW)
    state = scheduler.advance(state, ReviewOutcome.CORRECT, NOW + timedelta(seconds=30))

    paused_at = NOW + timedelta(days=3)
    paused = scheduler.pause(state, paused_at)

    assert paused.rung == state.rung
    assert paused.updated_at == paused_at
    # due_at recomputes from the pause moment, not from the original
    # transition — resuming after three days must not instantly fire.
    assert scheduler.due_at(paused) == paused_at + LADDER_OFFSETS[1][1]


# --- The FSRS handoff (TODO 0's "one bounded handoff, not interval inflation") ---


def test_micro_recalls_never_call_the_long_term_scheduler():
    """Climbing the whole ladder must not touch ReviewState at all — only
    `graduate()` does, and only once."""
    scheduler = AcquisitionScheduler()
    state = scheduler.start(word_id=1, user_id=1, now=NOW)
    t = NOW
    for _ in range(len(LADDER_OFFSETS[1])):
        t += timedelta(hours=1)
        state = scheduler.advance(state, ReviewOutcome.CORRECT, t)
    assert state.graduated is True
    # Nothing above ever constructed or mutated a ReviewState — this test
    # documents that guarantee by construction rather than by mocking.


def test_graduate_calls_the_long_term_scheduler_exactly_once_as_a_correct_review():
    calls = []

    class RecordingScheduler:
        def schedule_next(self, state, outcome):
            calls.append(outcome)
            return FSRSScheduler().schedule_next(state, outcome)

    before = _review_state()
    after = graduate(before, RecordingScheduler())

    assert calls == [ReviewOutcome.CORRECT]
    assert after.repetitions == before.repetitions + 1
    assert after.last_reviewed_at is not None


def test_graduate_with_fsrs_actually_advances_stability():
    before = _review_state()
    after = graduate(before, FSRSScheduler())
    assert after.stability is not None
    assert after.interval_days > 0
