"""Job body that notifies due acquisition rungs (#180, issue #184 TODO 2).

Runs on a scheduler worker thread, outside any request, mirroring
`reminder_dispatch.py`'s shape: one database session for the duration of
one poll, every due ladder claimed exclusively so two instances sharing a
job store cannot both notify for the same rung.
"""
from __future__ import annotations

import logging
from typing import Callable

from sqlalchemy.orm import Session

from app.application.use_cases.acquisition import DispatchOneAcquisitionReminderUseCase
from app.domain.services.notification_channel import NotificationChannel
from app.domain.value_objects import utcnow
from app.infrastructure.job_claims import claim
from app.infrastructure.repositories import (
    SqlAlchemyAcquisitionStateRepository,
    SqlAlchemyRecallSettingsRepository,
    SqlAlchemyUserRepository,
)

logger = logging.getLogger(__name__)

JOB_ID = "dispatch_acquisition_reminders"


def _occurrence_key(rung: int, updated_at) -> str:
    """Names the firing this dispatch belongs to: the ladder's own rung and
    the moment it became due at, not the wall clock the poll happened to
    run at. Two instances polling a few seconds apart compute the same key
    for the same firing; the *next* rung (a new updated_at) is a genuinely
    different occurrence, not a duplicate of this one."""
    return f"{rung}:{updated_at.isoformat()}"


class AcquisitionDispatcher:
    """Callable job body: `dispatcher()` notifies every due, not-yet-
    graduated ladder across every account, once each."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        channel: NotificationChannel,
        exclusive: bool = True,
    ):
        self.session_factory = session_factory
        self.channel = channel
        # Off only where there is provably one scheduler (tests). See
        # ReminderDispatcher's identical parameter for why.
        self.exclusive = exclusive

    def __call__(self) -> None:
        db = self.session_factory()
        try:
            acquisition_repo = SqlAlchemyAcquisitionStateRepository(db)
            due = acquisition_repo.list_due(utcnow())
            for state in due:
                try:
                    if self.exclusive and not self._claim(db, state):
                        continue
                    channel = getattr(self.channel, "for_word", None)
                    DispatchOneAcquisitionReminderUseCase(
                        SqlAlchemyUserRepository(db),
                        SqlAlchemyRecallSettingsRepository(db),
                        channel(state.word_id) if channel else self.channel,
                    ).execute(state)
                except Exception:  # noqa: BLE001 - one bad ladder must not stop the rest
                    logger.exception(
                        "acquisition dispatch failed for user %s word %s", state.user_id, state.word_id
                    )
        finally:
            db.close()

    def _claim(self, db: Session, state) -> bool:
        job_key = f"acquisition:{state.user_id}:{state.word_id}"
        return claim(db, job_key, _occurrence_key(state.rung, state.updated_at))
