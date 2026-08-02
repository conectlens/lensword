"""Concrete NotificationChannel adapters.

LogNotificationChannel is the starting adapter named in ROADMAP.md Phase
0.1 — it satisfies the port so calling code has something real to depend on
before a credentialed push/email/desktop provider exists (Phase 2).

DesktopNotificationChannel is the Phase 2.2 desktop adapter (issue #27).
"""
from __future__ import annotations

import logging
from typing import Callable

from sqlalchemy.orm import Session

from app.domain.entities import DesktopNotification, User
from app.domain.services.notification_channel import NotificationChannel
from app.domain.value_objects import Channel
from app.infrastructure.repositories import SqlAlchemyDesktopNotificationRepository

logger = logging.getLogger(__name__)


class LogNotificationChannel:
    def send(self, user: User, message: str, channel: str) -> None:
        logger.info("notification[%s] to %s: %s", channel, user.username, message)


class DesktopNotificationChannel:
    """Records desktop notifications for collection by a desktop shell.

    ADR 0002 chose a remote-only desktop app, which is what makes this an
    outbox rather than a call into an OS notification API. The backend
    generally runs on a different machine from the notification tray, so
    "deliver a desktop notification" can only mean "durably record that one is
    owed, and let the shell that owns the tray collect it". Drawing the toast
    is the shell's job (issue #31).

    Only the `desktop` channel is handled here; everything else is passed to
    `fallback`. Composing this over LogNotificationChannel therefore leaves
    push, email and in-app behaving exactly as before — worth stating
    explicitly, because the alternative (swallowing the other channels) would
    silently stop three of the four delivery routes the moment this adapter
    was wired in.

    The write commits on its own. The caller is ReminderDispatcher, running on
    a scheduler worker thread with a session it owns for the duration of one
    delivery and closes without committing; a row left uncommitted here would
    simply be lost.
    """

    def __init__(
        self,
        session_factory: Callable[[], Session],
        fallback: NotificationChannel | None = None,
    ):
        self.session_factory = session_factory
        self.fallback = fallback or LogNotificationChannel()

    def send(self, user: User, message: str, channel: str) -> None:
        if channel != Channel.DESKTOP.value:
            self.fallback.send(user, message, channel)
            return
        if user.id is None:
            # An unsaved user has nothing to scope the outbox row to. Logged
            # rather than raised: a failed notification must not take down the
            # scheduler job that produced it.
            logger.error("desktop notification skipped: user %r has no id", user.username)
            return

        db = self.session_factory()
        try:
            SqlAlchemyDesktopNotificationRepository(db).add(
                DesktopNotification(id=None, user_id=user.id, message=message)
            )
            db.commit()
            logger.info("desktop notification queued for %s", user.username)
        except Exception:  # noqa: BLE001 - a failed delivery must not kill the scheduler
            db.rollback()
            logger.exception("desktop notification could not be queued for %s", user.username)
        finally:
            db.close()
