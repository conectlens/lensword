"""Job body for a scheduled reminder.

Runs on a scheduler worker thread, outside any request, so it owns its own
database session for the duration of one delivery rather than borrowing a
request-scoped one.
"""
from __future__ import annotations

import logging
from typing import Callable

from sqlalchemy.orm import Session

from app.application.use_cases.reminders import DeliverReminderUseCase
from app.domain.services.notification_channel import NotificationChannel
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

    def __init__(self, session_factory: Callable[[], Session], channel: NotificationChannel):
        self.session_factory = session_factory
        self.channel = channel

    def __call__(self, reminder_id: int) -> None:
        db = self.session_factory()
        try:
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
