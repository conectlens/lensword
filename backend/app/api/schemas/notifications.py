"""Request/response shapes for the desktop notification outbox (issue #27)."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.domain.value_objects import NotificationAction


class DesktopNotificationResponse(BaseModel):
    id: int
    message: str
    created_at: datetime
    # The shell renders `title`/`body`; `message` is kept for the shells that
    # shipped before actions existed and read only that.
    title: str
    body: str
    # Which of the closed action set this notification offers. A shell shows
    # buttons for the ones it recognises and ignores the rest, so adding an
    # action later does not require every installed shell to update first.
    actions: list[str]
    # After this the actions are refused. Null means they never lapse.
    expires_at: datetime | None = None


class PendingDesktopNotificationsResponse(BaseModel):
    notifications: list[DesktopNotificationResponse]
    has_more: bool
    # Bumped when the meaning of a delivered payload changes. A shell older
    # than the backend needs to tell "I do not understand this" apart from
    # "this is the shape I know, with a new field in it".
    payload_version: int


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


class NotificationActionRequest(BaseModel):
    # Constrained to the enum, so an unrecognised id is a 422 rather than a
    # recorded action nothing knows how to carry out.
    action: NotificationAction


class NotificationActionResponse(BaseModel):
    # The action that now stands. For a repeated callback this is the original
    # one, which is not necessarily the one that was just requested.
    action: NotificationAction
    # False when this notification had already been answered — the call was a
    # duplicate and changed nothing.
    applied: bool
    # Whether the shell should bring the review UI forward.
    open_review: bool
