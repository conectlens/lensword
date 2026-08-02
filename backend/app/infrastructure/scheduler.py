"""Background job scheduler (infrastructure).

A fresh AsyncIOScheduler is created on every app startup rather than reused
across restarts: APScheduler schedulers are not safely restartable once shut
down, so the FastAPI lifespan owns exactly one instance per run (see
app.main.lifespan).

The *jobs* do persist across restarts (ROADMAP 4.2): the scheduler is given a
SQLAlchemy job store by default. Persistence and exclusivity are separate
problems, though — a shared job store hands the same due job to every
instance polling it. The second half lives in app.infrastructure.job_claims.
"""
from __future__ import annotations

import logging
from typing import Callable

from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.infrastructure.db import engine
from app.domain.services.notification_channel import NotificationChannel
from app.infrastructure.jobs import dev_heartbeat
from app.infrastructure.notifications import LogNotificationChannel
from app.infrastructure.reminders import restore_reminder_jobs

logger = logging.getLogger(__name__)


def create_scheduler(settings: Settings | None = None) -> AsyncIOScheduler:
    """Build the scheduler, with a persistent job store unless told otherwise.

    A database job store makes registered jobs survive a restart, which the
    in-memory default cannot. It does *not* make firing exclusive: every
    instance polling the same store sees the same due jobs and will run them.
    That half is handled per dispatch in app.infrastructure.job_claims, and
    neither piece is sufficient alone.

    APScheduler creates and manages its own `apscheduler_jobs` table, so it is
    deliberately absent from the Alembic migrations — the library owns that
    schema and changes it between versions.
    """
    settings = settings or get_settings()
    if settings.scheduler_job_store == "memory":
        return AsyncIOScheduler()
    return AsyncIOScheduler(
        jobstores={"default": SQLAlchemyJobStore(engine=engine)},
        # A job whose previous run is still going is not started again. With
        # several instances sharing one store this matters more than it did
        # in-process, where only one worker pool could ever be involved.
        job_defaults={"coalesce": True, "max_instances": 1},
    )


def register_jobs(
    scheduler: AsyncIOScheduler,
    settings: Settings,
    session_factory: Callable[[], Session] | None = None,
    channel: NotificationChannel | None = None,
) -> None:
    """Register all background jobs. Called once per app startup.

    Reminder jobs live only in memory, so the enabled reminders in the
    database are re-registered here on every start. Without a session factory
    (unit tests, or any caller with no database) only the environment's static
    jobs are registered.

    Restoring reminders is contained: they are a nudge, not the product, so no
    failure in reading or scheduling them is allowed to stop the application
    from starting. A backend that will not boot serves nobody, least of all the
    user whose reminders are unreadable.
    """
    if settings.environment == "development":
        scheduler.add_job(dev_heartbeat.run, "interval", seconds=10, id="dev_heartbeat")
    if session_factory is None:
        return

    try:
        restore_reminder_jobs(scheduler, session_factory, channel or LogNotificationChannel())
    except Exception:  # noqa: BLE001 - startup must survive a broken reminders table
        logger.exception("reminder jobs could not be restored; starting without them")
