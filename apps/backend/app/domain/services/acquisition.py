"""Graduated same-day acquisition loop (#180, issue #184).

## The two-horizon model (TODO 0)

`spaced_repetition.py` (`SpacedRepetitionScheduler`/`FSRSScheduler`) is the
single owner of day-scale and long-term intervals for every word, diagnosed
or not — that ownership is unconditional and this module never calls
`Scheduler.schedule_next` per rung. `AcquisitionScheduler` below is a second,
separate strategy that only ever operates on the seconds-to-hours horizon of
`AcquisitionState`, an ephemeral ladder position that is not itself a review
interval. The two meet exactly once, at `graduate()`: a single bounded call
into the long-term scheduler when the ladder finishes, not a per-rung
mutation. This is the ADR 0007 boundary this epic keeps re-stating, applied
to its third and final owner.

## Why graduation needs a real gap, not just "reached the last rung" (TODO 0)

A learner who taps through every rung in the same minute has demonstrated
nothing about *delayed* recall — only that they can re-type an answer they
just saw. `_MIN_GRADUATION_GAP` requires real wall-clock time to have passed
since the ladder started before the final rung's success can graduate it,
independent of how many rungs were climbed. This is the same "not merely a
same-session repeat" bar #183's `_MEANINGFUL_GAP` sets for ForgettingRule,
applied here to the loop's own exit condition rather than to a diagnosis.

## The ladder is not claimed to be Ebbinghaus (TODO 1)

`LADDER_OFFSETS` is a conservative, hand-chosen graduated sequence inspired
by Pimsleur's spacing, not a fit to any forgetting-curve dataset — TODO 1
explicitly warns against overclaiming here, so the docstring says exactly
that rather than a more impressive-sounding justification.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

from app.domain.services.diagnosis_contracts import AcquisitionState, Diagnosis
from app.domain.services.spaced_repetition import Scheduler
from app.domain.value_objects import ReviewOutcome, ReviewState

LADDER_POLICY_VERSION = 1

# Rung `i`'s offset is how long after the *previous* rung's success it
# becomes due — graduated within a single day, the same seconds-to-hours
# horizon TODO 0 asks `AcquisitionScheduler` to own. Six rungs: immediate
# re-test, then five widening gaps ending same-day.
LADDER_OFFSETS: dict[int, tuple[timedelta, ...]] = {
    1: (
        timedelta(seconds=30),
        timedelta(minutes=5),
        timedelta(minutes=20),
        timedelta(hours=1),
        timedelta(hours=6),
        timedelta(hours=20),
    ),
}

# See the module docstring: a ladder cannot graduate faster than this,
# regardless of rung count, so completing it quickly never counts as
# demonstrated delayed recall.
_MIN_GRADUATION_GAP = timedelta(hours=1)

# A rung failure drops the ladder back this many rungs rather than all the
# way to zero — TODO 1's "adapt intervals using failure/success", bounded so
# one bad answer late in the ladder does not erase most of a session's
# progress, and never below rung 0.
_BACKOFF_RUNGS = 2


class AcquisitionEntryReason(str, Enum):
    """Why a word entered the loop (TODO 4). Recorded on the state so the
    review experience can say why (TODO 3) without re-deriving it."""

    NEW_ITEM = "new_item"
    WEAK_ACQUISITION_DIAGNOSIS = "weak_acquisition_diagnosis"
    EXPLICIT_USER_CHOICE = "explicit_user_choice"


def should_enter_acquisition(
    *,
    is_new_word: bool,
    diagnosis: Diagnosis | None = None,
    explicit_choice: bool = False,
) -> AcquisitionEntryReason | None:
    """TODO 4's routing decision: which failures graduate into this loop,
    and which do not.

    Explicit choice always wins — a learner who asked for this is not
    second-guessed by inferred state. Semantic confusion is deliberately
    excluded: TODO 4 says "do not use the same policy for semantic
    confusion", and #185's contrast intervention (the strategy actually
    suited to two words being mixed up) does not exist yet — routing
    confusion here anyway would mean rehearsing one word in isolation for a
    failure mode that is fundamentally about *two* words, which does not
    help and would need undoing once #185 ships.
    """
    if explicit_choice:
        return AcquisitionEntryReason.EXPLICIT_USER_CHOICE
    if diagnosis is not None and diagnosis.outcome == "weak_acquisition":
        return AcquisitionEntryReason.WEAK_ACQUISITION_DIAGNOSIS
    if is_new_word:
        return AcquisitionEntryReason.NEW_ITEM
    return None


@dataclass(frozen=True, slots=True)
class RungOutcome:
    """One micro-recall's result, distinct from `ReviewOutcome` only in
    that this module never persists it as one — TODO 0's "micro-recalls do
    not each mutate FSRS" applies to storage, not just scheduling."""

    outcome: ReviewOutcome


class AcquisitionScheduler:
    """Pure strategy over `AcquisitionState` — no I/O, no clock of its own
    (every method takes `now` explicitly), testable under a fixed clock
    exactly the way #183's diagnosis rules are."""

    def start(
        self,
        word_id: int,
        user_id: int,
        now: datetime,
        entry_reason: AcquisitionEntryReason | None = None,
        operation_id: str | None = None,
    ) -> AcquisitionState:
        return AcquisitionState(
            word_id=word_id,
            user_id=user_id,
            rung=0,
            ladder_version=LADDER_POLICY_VERSION,
            started_at=now,
            updated_at=now,
            graduated=False,
            entry_reason=entry_reason.value if entry_reason is not None else None,
            operation_id=operation_id,
        )

    def due_at(self, state: AcquisitionState) -> datetime:
        """When this ladder's current rung becomes due next."""
        offsets = LADDER_OFFSETS[state.ladder_version]
        index = min(state.rung, len(offsets) - 1)
        return state.updated_at + offsets[index]

    def advance(
        self, state: AcquisitionState, outcome: ReviewOutcome, now: datetime, operation_id: str | None = None
    ) -> AcquisitionState:
        """One rung transition. Never touches `ReviewState` — see the
        module docstring; the caller is responsible for calling `graduate`
        exactly once when the returned state's `graduated` is True."""
        if state.graduated:
            return state

        offsets = LADDER_OFFSETS[state.ladder_version]
        if outcome is ReviewOutcome.CORRECT:
            next_rung = state.rung + 1
            at_final_rung = next_rung >= len(offsets)
            graduated = at_final_rung and (now - state.started_at) >= _MIN_GRADUATION_GAP
            # A ladder that reached the end too fast to graduate stays
            # parked one below the end rather than looping — TODO 0's gap
            # requirement is about *when* graduation counts, not a reason
            # to keep demanding more correct answers past the ladder's own
            # length.
            rung = min(next_rung, len(offsets) - 1) if not graduated else next_rung
        else:
            rung = max(0, state.rung - _BACKOFF_RUNGS)
            graduated = False

        return AcquisitionState(
            word_id=state.word_id,
            user_id=state.user_id,
            rung=rung,
            ladder_version=state.ladder_version,
            started_at=state.started_at,
            updated_at=now,
            graduated=graduated,
            entry_reason=state.entry_reason,
            operation_id=operation_id,
        )

    def pause(self, state: AcquisitionState, now: datetime) -> AcquisitionState:
        """TODO 1's pause: freezes the ladder by moving `updated_at`
        forward without changing rung, so `due_at` recomputes from the
        moment it resumes rather than staying stuck in the past and firing
        a storm of overdue notifications the instant it is unpaused."""
        return AcquisitionState(
            word_id=state.word_id, user_id=state.user_id, rung=state.rung,
            ladder_version=state.ladder_version, started_at=state.started_at,
            updated_at=now, graduated=state.graduated, entry_reason=state.entry_reason,
        )


def graduate(review_state: ReviewState, scheduler: Scheduler) -> ReviewState:
    """The single bounded handoff (TODO 0): one call into the account's
    real long-term scheduler (SM-2 or FSRS, whichever `RecallSettings`
    names), exactly once per ladder, as a CORRECT review — a completed
    ladder is by definition a successful recall. Never called per rung.
    """
    return scheduler.schedule_next(review_state, ReviewOutcome.CORRECT)
