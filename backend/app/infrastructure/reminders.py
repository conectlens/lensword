"""APScheduler adapter for the ReminderScheduler port.

Every reminder maps to exactly one job whose id is derived from the
reminder's identity, so re-registering it (on update, or when jobs are
restored at startup) replaces the existing job instead of stacking a second
one — the difference between a reminder that fires once and one that fires
twice.

Trigger times are registered in UTC explicitly rather than in the scheduler's
default local time zone, matching the naive-UTC convention the domain stores
them in (see app.domain.value_objects.utcnow). Note that this job store lives
in the process: running more than one backend instance would fire each
reminder once per instance. Making that safe is a Phase 4 concern (durable,
horizontally-safe job store).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Callable

from apscheduler.schedulers.base import BaseScheduler
from apscheduler.triggers.base import BaseTrigger
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from sqlalchemy.orm import Session

from app.domain.entities import Reminder
from app.domain.exceptions import DomainError
from app.domain.services.notification_channel import NotificationChannel
from app.domain.value_objects import Recurrence, utcnow
from app.infrastructure.jobs.reminder_dispatch import ReminderDispatcher
from app.infrastructure.repositories import SqlAlchemyReminderRepository

logger = logging.getLogger(__name__)

_JOB_ID_PREFIX = "reminder"

# A reminder is a nudge, not a transaction: if the scheduler was busy when it
# came due, delivering it a few minutes late is still useful, but every missed
# run must collapse into a single notification rather than a burst.
_MISFIRE_GRACE_SECONDS = 300


def reminder_job_id(reminder_id: int) -> str:
    return f"{_JOB_ID_PREFIX}:{reminder_id}"


class ApSchedulerReminderScheduler:
    def __init__(
        self,
        scheduler: BaseScheduler,
        dispatch: Callable[[int], None],
        clock: Callable[[], datetime] = utcnow,
    ):
        self.scheduler = scheduler
        self.dispatch = dispatch
        self.clock = clock

    def schedule(self, reminder: Reminder) -> None:
        if reminder.id is None:
            raise ValueError("A reminder must be persisted before its job can be registered")
        # `replace_existing` alone is not enough: before the scheduler is
        # started APScheduler only queues jobs and applies the replacement at
        # start time, so a job added twice beforehand is visible twice in the
        # meantime. Removing first makes registration idempotent in either
        # state, which is what the exactly-once guarantee rests on.
        self.unschedule(reminder.id)
        self.scheduler.add_job(
            self.dispatch,
            trigger=self._trigger_for(reminder),
            args=[reminder.id],
            id=reminder_job_id(reminder.id),
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            misfire_grace_time=_MISFIRE_GRACE_SECONDS,
        )

    def unschedule(self, reminder_id: int) -> None:
        job = self.scheduler.get_job(reminder_job_id(reminder_id))
        if job is not None:
            job.remove()

    def _trigger_for(self, reminder: Reminder) -> BaseTrigger:
        at = reminder.time_of_day
        if reminder.recurrence is Recurrence.ONCE:
            run_date = reminder.next_occurrence(self.clock()).replace(tzinfo=timezone.utc)
            return DateTrigger(run_date=run_date)
        return CronTrigger(hour=at.hour, minute=at.minute, second=at.second, timezone=timezone.utc)


def build_reminder_scheduler(
    scheduler: BaseScheduler,
    session_factory: Callable[[], Session],
    channel: NotificationChannel,
) -> ApSchedulerReminderScheduler:
    return ApSchedulerReminderScheduler(scheduler, dispatch=ReminderDispatcher(session_factory, channel))


def restore_reminder_jobs(
    scheduler: BaseScheduler,
    session_factory: Callable[[], Session],
    channel: NotificationChannel,
) -> None:
    """Re-register a job for every enabled reminder.

    Jobs are held in memory only, so they do not survive a restart; the
    database is the record of what should be scheduled. One unusable row is
    logged and skipped rather than left to abort the whole restore.
    """
    adapter = build_reminder_scheduler(scheduler, session_factory, channel)
    db = session_factory()
    try:
        reminders = SqlAlchemyReminderRepository(db).list_enabled()
    finally:
        db.close()

    for reminder in reminders:
        try:
            adapter.schedule(reminder)
        except (DomainError, ValueError):
            logger.exception("reminder %s could not be scheduled and was skipped", reminder.id)
