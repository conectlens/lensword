"""Spaced-repetition scheduling domain service.

Implemented as a Strategy (GRASP: Protected Variation / Polymorphism): the
Word entity depends on the `Scheduler` protocol, not on SM-2 specifically.
A different algorithm (e.g. FSRS) can be introduced later as another
implementation of the same protocol without touching Word or any use case.
"""
from __future__ import annotations

from datetime import timedelta
from math import exp, log
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
            stability=state.stability,
        )

    @staticmethod
    def _next_ease_factor(current: float, quality: int) -> float:
        updated = current + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
        return max(_MIN_EASE_FACTOR, round(updated, 4))

    @staticmethod
    def _clamp(value: int, lo: int, hi: int) -> int:
        return max(lo, min(hi, value))


class FSRSScheduler:
    """Small FSRS-style scheduler strategy.

    It keeps the existing embedded review state compatible while scheduling
    from a target retrievability rather than SM-2's fixed first intervals.

    Stability — the interval at which retrievability decays to
    `target_retrievability` — is persisted on `ReviewState.stability` and
    compounded across reviews. It is deliberately not re-derived from
    `interval_days`: `interval_days = stability * -log(target_retrievability)`
    is a fraction of stability (~0.105x at the default 0.9 target), so reading
    it back as the next stability collapses growth to a fixed point after a
    couple of reviews. See ADR 0004.
    """
    target_retrievability = 0.9
    # Floor on stability itself, not on the derived interval: a new word's
    # first stability estimate starts here, and no review may push stability
    # below it. Intervals are allowed to be sub-day early on — that is a
    # correct reflection of low confidence, not a bug — so nothing clamps
    # interval_days directly.
    _STABILITY_MIN = 1.0

    def schedule_next(self, state: ReviewState, outcome: ReviewOutcome) -> ReviewState:
        stability = state.stability if state.stability is not None else self._STABILITY_MIN
        if outcome == ReviewOutcome.CORRECT:
            stability *= 1.8 + min(state.repetitions, 10) * 0.08
            repetitions = state.repetitions + 1
        elif outcome == ReviewOutcome.SKIPPED:
            stability *= 0.7
            repetitions = max(0, state.repetitions - 1)
        else:
            stability *= 0.45
            repetitions = 0
        stability = max(self._STABILITY_MIN, stability)
        interval_days = round(min(_MAX_INTERVAL_DAYS, stability * -log(self.target_retrievability)), 2)
        now = utcnow()
        return ReviewState(
            strength=SpacedRepetitionScheduler._clamp(state.strength + _STRENGTH_DELTA[outcome], 0, 100),
            ease_factor=state.ease_factor,
            interval_days=interval_days,
            repetitions=repetitions,
            due_at=now + timedelta(days=interval_days),
            last_reviewed_at=now,
            stability=stability,
        )

    @classmethod
    def retrievability(cls, state: ReviewState) -> float:
        if state.last_reviewed_at is None:
            return 0.0
        elapsed = max(0.0, (utcnow() - state.last_reviewed_at).total_seconds() / 86400)
        stability = state.stability if state.stability is not None else cls._STABILITY_MIN
        return round(exp(-elapsed / max(cls._STABILITY_MIN, stability)), 4)
