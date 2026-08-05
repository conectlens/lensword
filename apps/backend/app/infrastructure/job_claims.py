"""Exactly-once execution for scheduled jobs across concurrent instances.

ROADMAP 4.2 (#20). Two problems hide behind "durable, multi-instance-safe
scheduler", and they need different answers:

*Durability* — jobs surviving a restart — is solved by giving APScheduler a
SQLAlchemy job store instead of the default in-memory one.

*Exclusivity* — the same job not running twice when two instances are up — is
not. APScheduler 3's job store has no locking: every scheduler polling it sees
the same due jobs and each will happily run them. That is what this module is
for.

The mechanism is a unique constraint. Each instance inserts a row naming the
job and the occurrence it is about to run; exactly one insert succeeds and the
losers get an integrity error and stand down. No advisory locks, no leader
election, and identical behaviour on Postgres and SQLite.
"""
from __future__ import annotations

import logging
from datetime import datetime, time, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.value_objects import utcnow
from app.infrastructure.models import SchedulerJobClaimModel

logger = logging.getLogger(__name__)

# Claims are evidence that a firing already happened, so they only need to
# outlive the window in which a duplicate could plausibly arrive — a restart, a
# misfire catch-up, a slow instance. A week is far beyond that and keeps the
# table from growing without bound.
CLAIM_RETENTION = timedelta(days=7)


def occurrence_key(local_now: datetime, trigger_time: time | None) -> str:
    """Name the firing this dispatch belongs to.

    Derived from the reminder's own schedule rather than from the clock. That
    distinction is the whole point: two instances fire a few seconds apart, and
    a misfire catch-up can run minutes late, so any key computed from "now"
    would differ between them and let the duplicate through. Anchoring to the
    scheduled time instead gives every instance the same answer for the same
    firing, whether it is early, on time, or late within the grace window.

    A `trigger_time` of None means the job has no recurring slot (a one-shot
    reminder), where the occurrence is the whole job and the date is enough.
    """
    if trigger_time is None:
        return "once"
    # Before today's slot means this is a late delivery of yesterday's, which
    # must claim yesterday's key rather than reserve tomorrow's.
    day = local_now.date()
    if local_now.time() < trigger_time:
        day = day - timedelta(days=1)
    return f"{day.isoformat()}T{trigger_time.isoformat(timespec='seconds')}"


def claim(db: Session, job_key: str, key: str) -> bool:
    """Try to take this occurrence. True if this caller may run it.

    Commits on success: the claim has to be visible to the other instances
    immediately, and holding it inside the caller's transaction would leave a
    window in which two instances both believe they won.
    """
    db.add(SchedulerJobClaimModel(job_key=job_key, occurrence_key=key, claimed_at=utcnow()))
    try:
        db.commit()
    except IntegrityError:
        # The expected outcome on every instance but one. Not an error.
        db.rollback()
        logger.info("job %s occurrence %s already claimed elsewhere; skipping", job_key, key)
        return False
    return True


def purge_expired_claims(db: Session, retention: timedelta = CLAIM_RETENTION) -> int:
    """Drop claims older than the window a duplicate could still arrive in."""
    cutoff = utcnow() - retention
    stale = db.query(SchedulerJobClaimModel).filter(SchedulerJobClaimModel.claimed_at < cutoff)
    removed = stale.count()
    stale.delete(synchronize_session=False)
    db.commit()
    return removed


def reminder_job_key(reminder_id: int) -> str:
    """Namespaced so a future job type cannot collide with a reminder id."""
    return f"reminder:{reminder_id}"
