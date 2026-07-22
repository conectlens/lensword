"""Spaced-repetition scheduling domain service.

Implemented as a Strategy (GRASP: Protected Variation / Polymorphism): the
Word entity depends on the `Scheduler` protocol, not on SM-2 specifically.
A different algorithm (e.g. FSRS) can be introduced later as another
implementation of the same protocol without touching Word or any use case.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Protocol

from app.domain.value_objects import ReviewOutcome, ReviewState, utcnow

_MIN_EASE_FACTOR = 1.3
_MAX_INTERVAL_DAYS = 365 * 5  # cap at 5 years — well past any practically useful review interval

# Flat strength deltas per outcome. Kept intentionally simple (rather than
# derived from interval/ease) so the "Learning Strength" shown in the UI is
# predictable and easy to reason about/test independently of the SM-2 curve.
_STRENGTH_DELTA = {
    ReviewOutcome.CORRECT: 15,
    ReviewOutcome.INCORRECT: -20,
    ReviewOutcome.SKIPPED: -5,
}

# SM-2 quality mapping for each outcome (0-5 scale from the original algorithm).
_QUALITY = {
    ReviewOutcome.CORRECT: 5,
    ReviewOutcome.INCORRECT: 2,
    ReviewOutcome.SKIPPED: 0,
}


class Scheduler(Protocol):
    def schedule_next(self, state: ReviewState, outcome: ReviewOutcome) -> ReviewState: ...


class SpacedRepetitionScheduler:
    """SM-2 (SuperMemo-2) implementation of the Scheduler protocol."""

    def schedule_next(self, state: ReviewState, outcome: ReviewOutcome) -> ReviewState:
        quality = _QUALITY[outcome]
        new_ease = self._next_ease_factor(state.ease_factor, quality)

        if quality < 3:
            repetitions = 0
            interval_days: float = 1
        else:
            if state.repetitions == 0:
                interval_days = 1
            elif state.repetitions == 1:
                interval_days = 6
            else:
                interval_days = round(state.interval_days * new_ease, 2)
            interval_days = min(interval_days, _MAX_INTERVAL_DAYS)
            repetitions = state.repetitions + 1

        new_strength = self._clamp(state.strength + _STRENGTH_DELTA[outcome], 0, 100)
        now = utcnow()

        return ReviewState(
            strength=new_strength,
            ease_factor=new_ease,
            interval_days=interval_days,
            repetitions=repetitions,
            due_at=now + timedelta(days=interval_days),
            last_reviewed_at=now,
        )

    @staticmethod
    def _next_ease_factor(current: float, quality: int) -> float:
        updated = current + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
        return max(_MIN_EASE_FACTOR, round(updated, 4))

    @staticmethod
    def _clamp(value: int, lo: int, hi: int) -> int:
        return max(lo, min(hi, value))
