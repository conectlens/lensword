"""Enter and advance the graduated acquisition ladder (#180, issue #184).

`EnterAcquisitionUseCase` is TODO 4's routing decision made real: it is
the one place a diagnosis, a new word, or an explicit user choice actually
starts a ladder. `SubmitAcquisitionAnswerUseCase` is the seam TODO 0
depends on — every micro-recall passes through here rather than through
`SubmitAnswerUseCase`, which is exactly how per-rung answers avoid calling
the long-term scheduler; only a graduating answer does, once.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

from app.domain.repositories import (
    AcquisitionStateRepository,
    RecallSettingsRepository,
    UserRepository,
    WordRepository,
)
from app.domain.services.acquisition import AcquisitionScheduler, graduate, should_enter_acquisition
from app.domain.services.diagnosis_contracts import AcquisitionState, Diagnosis
from app.domain.services.notification_channel import NotificationChannel
from app.domain.services.recall_delivery import RecallDeliveryPolicy
from app.domain.services.spaced_repetition import Scheduler
from app.domain.value_objects import ReviewOutcome, utcnow, zone_for


class EnterAcquisitionUseCase:
    """Idempotent by construction: a word already on an active (not yet
    graduated) ladder is returned as-is rather than restarted, so this can
    safely be called every time a diagnosis is produced or a word is
    created, not only the first time."""

    def __init__(self, acquisition_repo: AcquisitionStateRepository):
        self.acquisition_repo = acquisition_repo

    def execute(
        self,
        user_id: int,
        word_id: int,
        *,
        is_new_word: bool = False,
        diagnosis: Diagnosis | None = None,
        explicit_choice: bool = False,
        now: datetime | None = None,
    ) -> AcquisitionState | None:
        reason = should_enter_acquisition(
            is_new_word=is_new_word, diagnosis=diagnosis, explicit_choice=explicit_choice
        )
        if reason is None:
            return None

        existing = self.acquisition_repo.get_for_word(user_id, word_id)
        if existing is not None and not existing.graduated:
            return existing

        state = AcquisitionScheduler().start(word_id, user_id, now or utcnow(), entry_reason=reason)
        return self.acquisition_repo.upsert(state)


class SubmitAcquisitionAnswerUseCase:
    """One micro-recall. Returns `None` when there is no active ladder for
    this word (already graduated, never started, or cancelled) — the
    caller treats that as "nothing to submit to", not an error, since a
    client racing the ladder's own graduation is an expected timing, not a
    bug."""

    def __init__(self, acquisition_repo: AcquisitionStateRepository, word_repo: WordRepository, scheduler: Scheduler):
        self.acquisition_repo = acquisition_repo
        self.word_repo = word_repo
        self.scheduler = scheduler

    def execute(
        self,
        user_id: int,
        word_id: int,
        outcome: ReviewOutcome,
        operation_id: str | None = None,
        now: datetime | None = None,
    ) -> AcquisitionState | None:
        current = self.acquisition_repo.get_for_word(user_id, word_id)
        if current is None or current.graduated:
            return None

        now = now or utcnow()
        next_state = AcquisitionScheduler().advance(current, outcome, now, operation_id=operation_id)
        next_state = self.acquisition_repo.upsert(next_state)

        if next_state.graduated and not current.graduated:
            # The single bounded handoff (TODO 0) — exactly once, on the
            # transition that actually graduates, never re-run if this
            # method is called again against an already-graduated state
            # (the `current.graduated` guard above already returns early
            # for that case, so this branch only ever fires once per ladder).
            word = self.word_repo.get_by_id(word_id)
            if word is not None:
                word.review_state = graduate(word.review_state, self.scheduler)
                self.word_repo.update(word)

        return next_state


class CancelAcquisitionUseCase:
    """TODO 1's cancel: a learner (or an account-level toggle) can drop a
    word out of the loop entirely. Distinct from a failed rung, which
    backs off but stays on the ladder — this removes it."""

    def __init__(self, acquisition_repo: AcquisitionStateRepository):
        self.acquisition_repo = acquisition_repo

    def execute(self, user_id: int, word_id: int) -> None:
        self.acquisition_repo.delete_for_word(user_id, word_id)


ACQUISITION_MESSAGE = "A word is ready to stabilize."


class DispatchOneAcquisitionReminderUseCase:
    """One due rung's delivery decision (TODO 2/3), mirroring
    `DeliverReminderUseCase`'s shape exactly: re-read the account and its
    settings at fire time rather than trust anything captured earlier, and
    treat a since-disappeared subject as a no-op rather than an error — a
    dispatch racing a word deletion or a flag flip is an expected timing.

    Quiet hours reuse `RecallDeliveryPolicy`, the same decision every other
    delivery in this app already goes through, rather than a second,
    acquisition-specific quiet-hours rule that could drift from it.
    """

    def __init__(
        self,
        user_repo: UserRepository,
        settings_repo: RecallSettingsRepository,
        channel: NotificationChannel,
        clock: Callable[[], datetime] = utcnow,
    ):
        self.user_repo = user_repo
        self.settings_repo = settings_repo
        self.channel = channel
        self.clock = clock

    def execute(self, state: AcquisitionState) -> None:
        user = self.user_repo.get_by_id(state.user_id)
        if user is None or not user.is_active:
            return
        settings = self.settings_repo.get_by_user(state.user_id)
        if not (settings and settings.acquisition_loop_enabled):
            # The loop was turned off after this ladder started — the
            # ladder row itself is left alone (its owner may re-enable and
            # resume), but no further notification goes out for it.
            return

        now_local = (
            self.clock().replace(tzinfo=timezone.utc).astimezone(zone_for(user.time_zone)).replace(tzinfo=None)
        )
        allowed = RecallDeliveryPolicy.decide(settings, now_local)
        for target in sorted(allowed, key=lambda c: c.value):
            self.channel.send(user, ACQUISITION_MESSAGE, target.value)
