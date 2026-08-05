import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import Settings
from app.infrastructure.scheduler import create_scheduler, register_jobs


def test_create_scheduler_returns_an_asyncio_scheduler():
    scheduler = create_scheduler()
    assert isinstance(scheduler, AsyncIOScheduler)


def test_register_jobs_adds_heartbeat_job_in_development():
    scheduler = create_scheduler()
    register_jobs(scheduler, Settings(environment="development"))
    assert {job.id for job in scheduler.get_jobs()} == {"dev_heartbeat"}


def test_register_jobs_adds_no_jobs_outside_development():
    scheduler = create_scheduler()
    register_jobs(scheduler, Settings(environment="production"))
    assert scheduler.get_jobs() == []


def test_scheduler_lifecycle_is_repeatable_across_simulated_restarts():
    async def _start_and_shutdown_once():
        scheduler = create_scheduler()
        register_jobs(scheduler, Settings(environment="development"))
        scheduler.start()
        assert scheduler.running
        scheduler.shutdown(wait=False)
        await asyncio.sleep(0)  # AsyncIOScheduler defers the state flip via call_soon_threadsafe
        assert not scheduler.running

    for _ in range(3):
        asyncio.run(_start_and_shutdown_once())


def test_scheduler_is_started_and_running_during_app_lifespan(client):
    from app.main import app

    assert app.state.scheduler.running


def test_development_environment_configures_info_level_logging():
    """Without explicit configuration, the root logger defaults to WARNING and
    silently drops the dev_heartbeat job's INFO-level output."""
    from app.main import app  # noqa: F401  (import triggers module-level logging config)

    assert logging.getLogger().getEffectiveLevel() <= logging.INFO
