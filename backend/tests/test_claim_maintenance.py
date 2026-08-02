"""The claims table is pruned, and pruning cannot take the scheduler down.

`scheduler_job_claims` (issue #20) gets a row per firing and nothing reads it
back afterwards. `purge_expired_claims` existed from the start but nothing
called it, so the table was append-only for the life of a deployment — the
kind of defect that is invisible until a table is large.
"""
from __future__ import annotations

from datetime import timedelta

from apscheduler.schedulers.background import BackgroundScheduler

from app.config import Settings
from app.domain.value_objects import utcnow
from app.infrastructure.job_claims import CLAIM_RETENTION
from app.infrastructure.jobs.claim_maintenance import JOB_ID, ClaimPurger
from app.infrastructure.models import SchedulerJobClaimModel
from app.infrastructure.scheduler import register_jobs


def _claim(db, key: str, age: timedelta):
    db.add(
        SchedulerJobClaimModel(
            job_key="reminder:1", occurrence_key=key, claimed_at=utcnow() - age
        )
    )
    db.commit()


def test_the_purge_job_drops_spent_claims_and_keeps_live_ones(db_session):
    _claim(db_session, "expired", CLAIM_RETENTION + timedelta(days=1))
    _claim(db_session, "recent", timedelta(hours=1))

    ClaimPurger(lambda: db_session)()

    remaining = [c.occurrence_key for c in db_session.query(SchedulerJobClaimModel).all()]
    assert remaining == ["recent"]


def test_a_failing_purge_does_not_propagate(caplog):
    """Housekeeping runs on the same scheduler that delivers reminders. A
    raised exception here would cost the user their notifications to reclaim
    disk nobody was waiting on."""

    class _Exploding:
        def __call__(self):
            return self

        def query(self, *_):
            raise RuntimeError("database is gone")

        def close(self):
            pass

    with caplog.at_level("ERROR"):
        ClaimPurger(_Exploding())()

    assert "could not be purged" in caplog.text


def test_an_empty_table_is_a_quiet_no_op(db_session, caplog):
    with caplog.at_level("INFO"):
        ClaimPurger(lambda: db_session)()

    assert "purged" not in caplog.text


def test_startup_registers_the_purge_job(db_session):
    """Registered rather than merely available — the whole defect was that the
    function existed and nothing invoked it."""
    scheduler = BackgroundScheduler()

    register_jobs(scheduler, Settings(environment="production", _env_file=None), lambda: db_session)

    assert scheduler.get_job(JOB_ID) is not None


def test_re_registering_does_not_stack_a_second_purge_job(db_session):
    """Every instance registers this at startup against a shared job store, so
    they have to converge on one job rather than add a copy each."""
    scheduler = BackgroundScheduler()
    settings = Settings(environment="production", _env_file=None)

    register_jobs(scheduler, settings, lambda: db_session)
    register_jobs(scheduler, settings, lambda: db_session)

    assert len([j for j in scheduler.get_jobs() if j.id == JOB_ID]) == 1
