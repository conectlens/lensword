"""Reminder-window recommendations (issue #89).

Two endpoints and a deliberate gap between them: reading a suggestion changes
nothing, and applying it is a separate call. The issue asks for
recommendations "for explicit acceptance" with fixed schedules as the default,
and separate operations are what make that true of the API rather than only of
the screen drawn on top of it.

This is the first HTTP surface reminders have. It is deliberately narrow —
creating and editing reminders is still not exposed (see #56) — so nothing
here can bring a reminder into existence, only move one that already does.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.api.deps import (
    CurrentUser,
    DesktopNotificationRepo,
    RecallSettingsRepo,
    ReminderRepo,
    UserRepo,
)
from app.api.schemas.reminder_windows import (
    AcceptReminderWindowRequest,
    ReminderWindowRecommendationResponse,
    ReminderWindowResponse,
)
from app.application.use_cases.reminder_windows import (
    AcceptReminderWindowUseCase,
    SuggestReminderWindowUseCase,
)
from app.domain.exceptions import EntityNotFoundError, PermissionDeniedError

router = APIRouter(prefix="/api/v1/reminders", tags=["reminders"])


def _suggester(
    reminders: ReminderRepo,
    notifications: DesktopNotificationRepo,
    settings_repo: RecallSettingsRepo,
    users: UserRepo,
) -> SuggestReminderWindowUseCase:
    return SuggestReminderWindowUseCase(reminders, notifications, settings_repo, users)


def _handle(exc: Exception) -> None:
    if isinstance(exc, PermissionDeniedError):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    if isinstance(exc, EntityNotFoundError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    raise exc


@router.get("/{reminder_id}/window-recommendation", response_model=ReminderWindowResponse)
def get_window_recommendation(
    reminder_id: int,
    current_user: CurrentUser,
    reminders: ReminderRepo,
    notifications: DesktopNotificationRepo,
    settings_repo: RecallSettingsRepo,
    users: UserRepo,
) -> ReminderWindowResponse:
    try:
        suggestion = _suggester(reminders, notifications, settings_repo, users).execute(
            current_user.id, reminder_id
        )
    except (EntityNotFoundError, PermissionDeniedError) as exc:
        _handle(exc)

    # 200 with `recommendation: null` rather than 404. Having no suggestion is
    # the ordinary answer — most accounts most of the time — and a 404 would
    # make "not enough evidence" indistinguishable from "no such reminder".
    if suggestion is None:
        return ReminderWindowResponse(recommendation=None)

    return ReminderWindowResponse(
        recommendation=ReminderWindowRecommendationResponse(
            reminder_id=suggestion.reminder_id,
            current_hour=suggestion.current_hour,
            suggested_hour=suggestion.recommendation.hour,
            suggested_rate=suggestion.recommendation.suggested_rate,
            current_rate=suggestion.recommendation.current_rate,
            suggested_sample=suggestion.recommendation.suggested_sample,
            current_sample=suggestion.recommendation.current_sample,
            # Carried so a user can check the reason against the numbers rather
            # than take the suggestion on trust.
            explanation=suggestion.explanation,
        )
    )


@router.post("/{reminder_id}/window-recommendation/accept", status_code=status.HTTP_204_NO_CONTENT)
def accept_window_recommendation(
    reminder_id: int,
    payload: AcceptReminderWindowRequest,
    current_user: CurrentUser,
    reminders: ReminderRepo,
    notifications: DesktopNotificationRepo,
    settings_repo: RecallSettingsRepo,
    users: UserRepo,
) -> None:
    suggester = _suggester(reminders, notifications, settings_repo, users)
    try:
        # The hour is re-derived rather than trusted. Without that this would
        # be an endpoint for setting a reminder to any hour at all under the
        # cover of accepting a recommendation, including one inside the
        # account's own quiet hours.
        AcceptReminderWindowUseCase(reminders, suggester).execute(
            current_user.id, reminder_id, payload.hour
        )
    except (EntityNotFoundError, PermissionDeniedError) as exc:
        _handle(exc)
