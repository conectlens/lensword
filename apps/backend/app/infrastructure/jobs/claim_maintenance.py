"""Job body that prunes spent scheduler claims.

`scheduler_job_claims` (issue #20) gets one row per job firing and nothing ever
read them back after the firing they guarded. Without this the table is
append-only for the life of the deployment — a reminder-heavy account adds a
row a day, forever, for a record whose usefulness expires within minutes.

Registered as its own job rather than folded into the dispatcher: pruning on
every delivery would put a table scan on the latency path of the thing being
delivered, to reclaim rows that nobody is waiting on.
"""
from __future__ import annotations

import logging
from typing import Callable

from sqlalchemy.orm import Session

from app.infrastructure.job_claims import purge_expired_claims

logger = logging.getLogger(__name__)

JOB_ID = "purge_scheduler_claims"


class ClaimPurger:
    """Callable job body: drops claims older than the retention window."""

    def __init__(self, session_factory: Callable[[], Session]):
        self.session_factory = session_factory

    def __call__(self) -> None:
        db = self.session_factory()
        try:
            removed = purge_expired_claims(db)
            if removed:
                logger.info("purged %d expired scheduler claim(s)", removed)
        except Exception:  # noqa: BLE001 - housekeeping must not kill the scheduler
            # Deliberately swallowed. A failed purge costs disk; a raised one
            # would take down the scheduler that delivers reminders.
            logger.exception("scheduler claims could not be purged")
        finally:
            db.close()
