"""Concrete NotificationChannel adapters.

LogNotificationChannel is the starting adapter named in ROADMAP.md Phase
0.1 — it satisfies the port so calling code has something real to depend on
before a credentialed push/email/desktop provider exists (Phase 2).
"""
from __future__ import annotations

import logging

from app.domain.entities import User

logger = logging.getLogger(__name__)


class LogNotificationChannel:
    def send(self, user: User, message: str, channel: str) -> None:
        logger.info("notification[%s] to %s: %s", channel, user.username, message)
