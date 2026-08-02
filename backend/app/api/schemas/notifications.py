"""Request/response shapes for the desktop notification outbox (issue #27)."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class DesktopNotificationResponse(BaseModel):
    id: int
    message: str
    created_at: datetime


class PendingDesktopNotificationsResponse(BaseModel):
    notifications: list[DesktopNotificationResponse]
    # True when the page was cut short by the limit, so a shell knows to
    # collect again rather than assuming it has drained the outbox.
    has_more: bool


class AcknowledgeDesktopNotificationsRequest(BaseModel):
    # Bounded to match the collection limit: an acknowledgement can never
    # legitimately name more ids than a single collection could return, and an
    # unbounded list is an unbounded IN clause.
    notification_ids: list[int] = Field(min_length=1, max_length=50)


class AcknowledgeDesktopNotificationsResponse(BaseModel):
    # How many rows this call actually moved from pending to delivered.
    # Deliberately not the length of the request: a repeated acknowledgement
    # reports 0, which is how a caller distinguishes a duplicate callback from
    # a first delivery.
    acknowledged: int
