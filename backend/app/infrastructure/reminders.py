"""APScheduler adapter for the ReminderScheduler port.

Every reminder maps to exactly one job whose id is derived from the
reminder's identity, so re-registering it (on update, or when jobs are
restored at startup) replaces the existing job instead of stacking a second
one — the difference between a reminder that fires once and one that fires
twice.

A reminder's trigger time is a wall-clock time on its owner's calendar, so
triggers are registered against that user's zone rather than the scheduler's
default local zone (issue #44). The zone is supplied by the caller: see the
ReminderScheduler port for why it is not read off the reminder.

Note that this job store lives in the process: running more than one backend
instance would fire each reminder once per instance. Making that safe is a
Phase 4 concern (durable, horizontally-safe job store).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Callable
from zoneinfo import ZoneInfo

from apscheduler.schedulers.base import BaseScheduler
from apscheduler.triggers.base import BaseTrigger
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from sqlalchemy.orm import Session

from app.domain.entities import Reminder
from app.domain.exceptions import DomainError
from app.domain.services.notification_channel import NotificationChannel
from app.domain.value_objects import (
    DEFAULT_TIME_ZONE,
    Recurrence,
    resolve_local_time,
    utcnow,
    zone_for,
)
from app.infrastructure.jobs.reminder_dispatch import ReminderDispatcher
from app.infrastructure.repositories import SqlAlchemyReminderRepository, SqlAlchemyUserRepository

logger = logging.getLogger(__name__)

_JOB_ID_PREFIX = "reminder"

# A reminder is a nudge, not a transaction: if the scheduler was busy when it
# came due, delivering it a few minutes late is still useful, but every missed
# run must collapse into a single notification rather than a burst.
_MISFIRE_GRACE_SECONDS = 300


def reminder_job_id(reminder_id: int) -> str:
    return f"{_JOB_ID_PREFIX}:{reminder_id}"


class LocalWallClockCronTrigger(CronTrigger):
    """CronTrigger that resolves DST edges the way the rest of the app does.

    APScheduler already agrees with the project's rule on an autumn fall-back:
    a doubled wall-clock time fires on the first occurrence, once. It differs
    on a spring-forward gap, where it returns the nonexistent local time
    carried at the pre-transition offset — a 02:30 reminder in a 02:00 -> 03:00
    jump then arrives at 03:30 rather than at 03:00.

    Either answer is defensible on its own, but one-shot reminders resolve
    through resolve_local_time and would land at 03:00, and two reminders set
    to the same wall-clock time arriving an hour apart because one recurs is
    not defensible. Re-resolving the fire time here keeps a single rule across
    both, and is a no-op on every other day of the year.
    """

    def get_next_fire_time(self, previous_fire_time, now):  # type: ignore[no-untyped-def]
        candidate = super().get_next_fire_time(previous_fire_time, now)
        while candidate is not None:
            resolved = resolve_local_time(candidate.replace(tzinfo=None), self.timezone)
            if previous_fire_time is None or resolved > previous_fire_time:
                return resolved
            # A fall-back day offers the same wall clock twice, and both
            # readings resolve to the first instant — which has already fired.
            # Returning it again would leave the job permanently due and
            # deliver it in a loop, so the repeat is skipped rather than
            # re-fired. Fire times must strictly increase.
            candidate = super().get_next_fire_time(candidate, candidate)
        return None


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

    def schedule(self, reminder: Reminder, time_zone: str = DEFAULT_TIME_ZONE) -> None:
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
            trigger=self._trigger_for(reminder, zone_for(time_zone)),
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

    def _trigger_for(self, reminder: Reminder, zone: ZoneInfo) -> BaseTrigger:
        at = reminder.time_of_day
        if reminder.recurrence is Recurrence.ONCE:
            # "Next 09:00" has to be decided on the user's clock, not on UTC:
            # for a user far enough east, the next local 09:00 can fall on a
            # different UTC date than the naive comparison would pick.
            now_local = (
                self.clock().replace(tzinfo=timezone.utc).astimezone(zone).replace(tzinfo=None)
            )
            return DateTrigger(run_date=resolve_local_time(reminder.next_occurrence(now_local), zone))
        return LocalWallClockCronTrigger(
            hour=at.hour, minute=at.minute, second=at.second, timezone=zone
        )


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
        # Read every owner's zone up front rather than per reminder: a user
        # with several reminders would otherwise be fetched once for each.
        user_repo = SqlAlchemyUserRepository(db)
        zones: dict[int, str] = {}
        for user_id in {r.user_id for r in reminders}:
            user = user_repo.get_by_id(user_id)
            zones[user_id] = user.time_zone if user else DEFAULT_TIME_ZONE
    finally:
        db.close()

    for reminder in reminders:
        try:
            adapter.schedule(reminder, zones.get(reminder.user_id, DEFAULT_TIME_ZONE))
        except (DomainError, ValueError):
            logger.exception("reminder %s could not be scheduled and was skipped", reminder.id)
