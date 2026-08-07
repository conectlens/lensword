"""Desktop notification outbox endpoints (ROADMAP 2.2/3.2, issues #27, #88).

The desktop shell polls `GET /desktop-notifications` for what it owes the
tray, acts on one with `POST /desktop-notifications/{id}/action`, and
acknowledges what it has shown with `POST /desktop-notifications/ack`. All
three are scoped to the authenticated account; there is no endpoint that
reads or acts on another user's outbox.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import CurrentUser, DesktopNotificationRepo, RecallSettingsRepo
from app.api.schemas.notifications import (
    AcknowledgeDesktopNotificationsRequest,
    AcknowledgeDesktopNotificationsResponse,
    DesktopNotificationResponse,
    NotificationActionRequest,
    NotificationActionResponse,
    PendingDesktopNotificationsResponse,
)
from app.application.use_cases.notifications import (
    DEFAULT_COLLECTION_LIMIT,
    AcknowledgeDesktopNotificationsUseCase,
    CollectDesktopNotificationsUseCase,
    PerformNotificationActionUseCase,
)
from app.domain.entities import DesktopNotification, RecallSettings
from app.domain.exceptions import EntityNotFoundError, NotificationExpiredError
from app.domain.value_objects import NOTIFICATION_PAYLOAD_VERSION, NotificationAction

router = APIRouter(prefix="/api/v1", tags=["notifications"])

NOTIFICATION_TITLE = "LensWord"

# Shown instead of the real body when the account has asked for details to be
# hidden. A desktop toast is drawn on a lock screen, over a shared screen, or
# on a second monitor in an open office — none of which the person who set the
# reminder chose.
REDACTED_BODY = "A review is waiting."


def _to_response(
    notification: DesktopNotification, settings: RecallSettings
) -> DesktopNotificationResponse:
    body = REDACTED_BODY if settings.hide_notification_details else notification.message
    return DesktopNotificationResponse(
        id=notification.id,
        message=notification.message,
        created_at=notification.created_at,
        title=NOTIFICATION_TITLE,
        body=body,
        # Offered only while the notification can still be answered. A shell
        # that rendered buttons for an expired one would present three controls
        # that all return an error.
        actions=[] if notification.is_expired() else [a.value for a in NotificationAction],
        expires_at=notification.expires_at,
        companion_deep_link=notification.companion_deep_link,
    )


@router.get("/desktop-notifications", response_model=PendingDesktopNotificationsResponse)
def list_pending_desktop_notifications(
    current_user: CurrentUser,
    repo: DesktopNotificationRepo,
    settings_repo: RecallSettingsRepo,
    limit: int = Query(DEFAULT_COLLECTION_LIMIT, ge=1, le=50),
) -> PendingDesktopNotificationsResponse:
    # An account that never saved settings gets RecallSettings' own defaults,
    # matching what the settings screen shows it.
    settings = settings_repo.get_by_user(current_user.id) or RecallSettings(user_id=current_user.id)
    # Paused suppresses delivery without unsetting the schedule, so reminders
    # come back unchanged rather than needing to be rebuilt. The rows stay
    # pending: unpausing should not have lost them.
    if settings.notifications_paused:
        return PendingDesktopNotificationsResponse(
            notifications=[], has_more=False, payload_version=NOTIFICATION_PAYLOAD_VERSION
        )

    result = CollectDesktopNotificationsUseCase(repo).execute(current_user.id, limit)
    return PendingDesktopNotificationsResponse(
        notifications=[_to_response(n, settings) for n in result.notifications],
        has_more=result.has_more,
        payload_version=NOTIFICATION_PAYLOAD_VERSION,
    )


@router.post(
    "/desktop-notifications/{notification_id}/action", response_model=NotificationActionResponse
)
def act_on_desktop_notification(
    notification_id: int,
    payload: NotificationActionRequest,
    current_user: CurrentUser,
    repo: DesktopNotificationRepo,
) -> NotificationActionResponse:
    try:
        outcome = PerformNotificationActionUseCase(repo).execute(
            current_user.id, notification_id, payload.action
        )
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except NotificationExpiredError as exc:
        # 409, not 404 or 422: the notification is real and belongs to the
        # caller, it is simply too old to answer. A shell needs to tell that
        # apart from a bad id to choose between showing an error and quietly
        # dropping a stale OS callback.
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    return NotificationActionResponse(
        action=outcome.action, applied=outcome.applied, open_review=outcome.open_review
    )


@router.post("/desktop-notifications/ack", response_model=AcknowledgeDesktopNotificationsResponse)
def acknowledge_desktop_notifications(
    payload: AcknowledgeDesktopNotificationsRequest,
    current_user: CurrentUser,
    repo: DesktopNotificationRepo,
) -> AcknowledgeDesktopNotificationsResponse:
    # Ids that do not exist, belong to another account, or were already
    # acknowledged are simply not counted. Deliberately not a 404 or a 409: the
    # caller is an OS notification callback that is allowed to fire twice, and
    # the correct response to "I already knew that" is success.
    moved = AcknowledgeDesktopNotificationsUseCase(repo).execute(
        current_user.id, payload.notification_ids
    )
    return AcknowledgeDesktopNotificationsResponse(acknowledged=moved)
