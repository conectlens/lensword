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
from app.infrastructure.jobs.acquisition_dispatch import AcquisitionDispatcher
from app.infrastructure.jobs.acquisition_dispatch import JOB_ID as ACQUISITION_DISPATCH_JOB_ID
from app.infrastructure.jobs.claim_maintenance import JOB_ID as PURGE_CLAIMS_JOB_ID, ClaimPurger
from app.infrastructure.jobs.companion_task_dispatch import CompanionTaskExecutor
from app.infrastructure.jobs.companion_task_dispatch import JOB_ID as COMPANION_TASK_DISPATCH_JOB_ID
from app.infrastructure.notifications import LogNotificationChannel
from app.infrastructure.reminders import restore_reminder_jobs

logger = logging.getLogger(__name__)

# APScheduler's persistent SQLAlchemyJobStore identifies a job's callable by a
# plain "module:qualname" string (apscheduler.util.obj_to_ref) and re-derives
# it fresh on every load via that string alone — it does not, and cannot,
# serialize a *constructed* object's state through that path. Passing
# ClaimPurger(session_factory) directly as a job's func used to collapse to a
# reference to the bare ClaimPurger class (obj_to_ref has no way to name an
# instance, only a type), silently dropping the constructor argument; every
# future firing then called ClaimPurger() with no arguments and raised
# TypeError. That happened on the very first firing after add_job(), in the
# same process, not just after a real restart, since the store round-trips
# through this reference on every dispatch.
#
# The fix is to register plain, zero/primitive-argument top-level functions
# instead — references to those round-trip correctly — and keep the actual
# dispatcher instances (each closing over a live, unpicklable SQLAlchemy
# session_factory) as ordinary module globals that these functions read at
# call time. That is safe here specifically because every job in this store
# only ever runs inside the same process that registered it (see this
# module's own docstring); nothing about this relies on the instances
# themselves crossing a process boundary.
_claim_purger: ClaimPurger | None = None
_acquisition_dispatcher: AcquisitionDispatcher | None = None
_companion_task_executor: CompanionTaskExecutor | None = None


def _run_claim_purger() -> None:
    assert _claim_purger is not None, "register_jobs must run before this job can fire"
    _claim_purger()


def _run_acquisition_dispatcher() -> None:
    assert _acquisition_dispatcher is not None, "register_jobs must run before this job can fire"
    _acquisition_dispatcher()


def _run_companion_task_executor() -> None:
    assert _companion_task_executor is not None, "register_jobs must run before this job can fire"
    _companion_task_executor()


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

    # Housekeeping for the claims that make firing exclusive (issue #20).
    # Nothing reads a claim after the firing it guarded, so without this the
    # table only ever grows. Daily rather than hourly: the retention window is
    # a week, so the reclaimable volume changes slowly.
    #
    # Removed first, then added. `replace_existing` alone is not enough: before
    # the scheduler is started APScheduler only queues jobs and applies the
    # replacement at start time, so a job added twice beforehand is genuinely
    # there twice in the meantime. Same reasoning as
    # ApSchedulerReminderScheduler.schedule.
    global _claim_purger, _acquisition_dispatcher, _companion_task_executor
    if scheduler.get_job(PURGE_CLAIMS_JOB_ID) is not None:
        scheduler.remove_job(PURGE_CLAIMS_JOB_ID)
    _claim_purger = ClaimPurger(session_factory)
    scheduler.add_job(
        _run_claim_purger,
        "interval",
        days=1,
        id=PURGE_CLAIMS_JOB_ID,
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )

    try:
        restore_reminder_jobs(scheduler, session_factory, channel or LogNotificationChannel())
    except Exception:  # noqa: BLE001 - startup must survive a broken reminders table
        logger.exception("reminder jobs could not be restored; starting without them")

    # Polls for due acquisition rungs (#184 TODO 2) rather than a job
    # registered per ladder: ladders are created and destroyed constantly
    # as accounts progress, unlike reminders' small, slowly-changing set,
    # so a poll avoids registering and tearing down a scheduler job on
    # every rung transition. Five minutes: finer than that adds dispatch
    # load for no benefit against a ladder whose tightest gap (30 seconds)
    # nothing here claims to hit precisely — the notification is a nudge,
    # not the timer the client-side session itself is responsible for.
    if scheduler.get_job(ACQUISITION_DISPATCH_JOB_ID) is not None:
        scheduler.remove_job(ACQUISITION_DISPATCH_JOB_ID)
    _acquisition_dispatcher = AcquisitionDispatcher(session_factory, channel or LogNotificationChannel())
    scheduler.add_job(
        _run_acquisition_dispatcher,
        "interval",
        minutes=5,
        id=ACQUISITION_DISPATCH_JOB_ID,
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )

    # Advances every runnable companion task (#197 TODO 3). Ten seconds
    # rather than acquisition's five minutes: a companion task is
    # interactive — a user is plausibly waiting on it inside a live
    # session — where a due-word nudge is not. Nothing about correctness
    # depends on this exact interval; a slower poll only means slower
    # progress, never lost or duplicated work (see companion_task_dispatch's
    # module docstring for why).
    if scheduler.get_job(COMPANION_TASK_DISPATCH_JOB_ID) is not None:
        scheduler.remove_job(COMPANION_TASK_DISPATCH_JOB_ID)
    _companion_task_executor = CompanionTaskExecutor(session_factory)
    scheduler.add_job(
        _run_companion_task_executor,
        "interval",
        seconds=10,
        id=COMPANION_TASK_DISPATCH_JOB_ID,
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
