"""Demo job proving the scheduler is wired end-to-end; not a real feature."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def run() -> None:
    logger.info("scheduler heartbeat")
