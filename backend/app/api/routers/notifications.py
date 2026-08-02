"""Desktop notification outbox endpoints (ROADMAP 2.2, issue #27).

The desktop shell polls `GET /desktop-notifications` for what it owes the
tray and acknowledges with `POST /desktop-notifications/ack` once it has
drawn them. Both are scoped to the authenticated account; there is no
endpoint that reads another user's outbox.
"""
from __future__ import annotations

from fastapi import APIRouter, Query

from app.api.deps import CurrentUser, DesktopNotificationRepo
from app.api.schemas.notifications import (
    AcknowledgeDesktopNotificationsRequest,
    AcknowledgeDesktopNotificationsResponse,
    DesktopNotificationResponse,
    PendingDesktopNotificationsResponse,
)
from app.application.use_cases.notifications import (
    DEFAULT_COLLECTION_LIMIT,
    AcknowledgeDesktopNotificationsUseCase,
    CollectDesktopNotificationsUseCase,
)

router = APIRouter(prefix="/api/v1", tags=["notifications"])


@router.get("/desktop-notifications", response_model=PendingDesktopNotificationsResponse)
def list_pending_desktop_notifications(
    current_user: CurrentUser,
    repo: DesktopNotificationRepo,
    limit: int = Query(DEFAULT_COLLECTION_LIMIT, ge=1, le=50),
) -> PendingDesktopNotificationsResponse:
    result = CollectDesktopNotificationsUseCase(repo).execute(current_user.id, limit)
    return PendingDesktopNotificationsResponse(
        notifications=[
            DesktopNotificationResponse(id=n.id, message=n.message, created_at=n.created_at)
            for n in result.notifications
        ],
        has_more=result.has_more,
    )


@router.post("/desktop-notifications/ack", response_model=AcknowledgeDesktopNotificationsResponse)
def acknowledge_desktop_notifications(
    payload: AcknowledgeDesktopNotificationsRequest,
    current_user: CurrentUser,
    repo: DesktopNotificationRepo,
) -> AcknowledgeDesktopNotificationsResponse:
    # Ids that do not exist, belong to another account, or were already
    # acknowledged are simply not counted. This is deliberately not a 404 or a
    # 409: the caller is an OS notification callback that is allowed to fire
    # twice, and the correct response to "I already knew that" is success.
    moved = AcknowledgeDesktopNotificationsUseCase(repo).execute(
        current_user.id, payload.notification_ids
    )
    return AcknowledgeDesktopNotificationsResponse(acknowledged=moved)
