"""Job body for a scheduled reminder.

Runs on a scheduler worker thread, outside any request, so it owns its own
database session for the duration of one delivery rather than borrowing a
request-scoped one.
"""
from __future__ import annotations

import logging
from datetime import timezone
from typing import Callable

from sqlalchemy.orm import Session

from app.application.use_cases.reminders import DeliverReminderUseCase
from app.domain.services.notification_channel import NotificationChannel
from app.domain.value_objects import DEFAULT_TIME_ZONE, Recurrence, utcnow, zone_for
from app.infrastructure.job_claims import claim, occurrence_key, reminder_job_key
from app.infrastructure.repositories import (
    SqlAlchemyRecallSettingsRepository,
    SqlAlchemyReminderRepository,
    SqlAlchemyUserRepository,
)

logger = logging.getLogger(__name__)


class ReminderDispatcher:
    """Callable job body: `dispatcher(reminder_id)` delivers one reminder.

    Exceptions are logged and swallowed. APScheduler would otherwise only
    print the traceback and, for a recurring job, keep the failing job
    registered anyway — turning a transient database error into noise rather
    than into a lost or duplicated notification.
    """

    def __init__(
        self,
        session_factory: Callable[[], Session],
        channel: NotificationChannel,
        exclusive: bool = True,
    ):
        self.session_factory = session_factory
        self.channel = channel
        # Off only where there is provably one scheduler — the tests that
        # assert delivery behaviour rather than concurrency. Leaving it on
        # there would make every second call in a single test a no-op, since
        # the first would already hold the day's claim.
        self.exclusive = exclusive

    def __call__(self, reminder_id: int) -> None:
        db = self.session_factory()
        try:
            if self.exclusive and not self._claim(db, reminder_id):
                return
            DeliverReminderUseCase(
                SqlAlchemyReminderRepository(db),
                SqlAlchemyUserRepository(db),
                SqlAlchemyRecallSettingsRepository(db),
                self.channel,
            ).execute(reminder_id)
        except Exception:  # noqa: BLE001 - a failed delivery must not kill the scheduler
            logger.exception("reminder %s could not be delivered", reminder_id)
        finally:
            db.close()

    def _claim(self, db: Session, reminder_id: int) -> bool:
        """Take this firing, or report that another instance already has.

        The occurrence is named from the reminder's own schedule on its owner's
        clock, so every instance computes the same key for the same firing even
        though they read the wall clock at different moments.

        A reminder or user that has since disappeared is not claimed — it is
        left to the use case, which treats a job outliving its subject as a
        no-op rather than an error, and a claim row for a deleted reminder
        would only be litter.
        """
        reminder = SqlAlchemyReminderRepository(db).get_by_id(reminder_id)
        if reminder is None:
            return True
        user = SqlAlchemyUserRepository(db).get_by_id(reminder.user_id)
        zone = zone_for(user.time_zone if user else DEFAULT_TIME_ZONE)
        local_now = utcnow().replace(tzinfo=timezone.utc).astimezone(zone).replace(tzinfo=None)
        slot = None if reminder.recurrence is Recurrence.ONCE else reminder.time_of_day
        return claim(db, reminder_job_key(reminder_id), occurrence_key(local_now, slot))
