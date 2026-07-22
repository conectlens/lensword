"""Background job scheduler (infrastructure).

A fresh AsyncIOScheduler is created on every app startup rather than reused
across restarts: APScheduler schedulers are not safely restartable once shut
down, so the FastAPI lifespan owns exactly one instance per run (see
app.main.lifespan). Durable, cross-restart job persistence is a Phase 4
concern (multi-instance-safe scheduler), not this one.
"""
from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import Settings
from app.infrastructure.jobs import dev_heartbeat


def create_scheduler() -> AsyncIOScheduler:
    return AsyncIOScheduler()


def register_jobs(scheduler: AsyncIOScheduler, settings: Settings) -> None:
    """Register all background jobs. Called once per app startup."""
    if settings.environment == "development":
        scheduler.add_job(dev_heartbeat.run, "interval", seconds=10, id="dev_heartbeat")
