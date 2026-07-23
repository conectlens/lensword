"""Background job scheduler (infrastructure).

A fresh AsyncIOScheduler is created on every app startup rather than reused
across restarts: APScheduler schedulers are not safely restartable once shut
down, so the FastAPI lifespan owns exactly one instance per run (see
app.main.lifespan). Durable, cross-restart job persistence is a Phase 4
concern (multi-instance-safe scheduler), not this one.
"""
from __future__ import annotations

import logging
from typing import Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.orm import Session

from app.config import Settings
from app.domain.services.notification_channel import NotificationChannel
from app.infrastructure.jobs import dev_heartbeat
from app.infrastructure.notifications import LogNotificationChannel
from app.infrastructure.reminders import restore_reminder_jobs

logger = logging.getLogger(__name__)


def create_scheduler() -> AsyncIOScheduler:
    return AsyncIOScheduler()


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
