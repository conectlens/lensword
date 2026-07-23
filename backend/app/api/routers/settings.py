from fastapi import APIRouter, Request

from app.api.deps import CurrentUser, RecallSettingsRepo, ReminderRepo, UserRepo, WordRepo
from app.api.schemas.settings import (
    BadgeResponse,
    ProfileOverviewResponse,
    RecallSettingsResponse,
    RecallSettingsUpdateRequest,
)
from app.application.use_cases.settings import (
    GetProfileOverviewUseCase,
    GetRecallSettingsUseCase,
    UpdateRecallSettingsUseCase,
)
from app.application.use_cases.reminders import SetUserTimeZoneUseCase
from app.domain.entities import RecallSettings
from app.infrastructure.db import SessionLocal
from app.infrastructure.notifications import LogNotificationChannel
from app.infrastructure.reminders import build_reminder_scheduler

router = APIRouter(prefix="/api/v1", tags=["settings"])


def _settings_to_response(s: RecallSettings, time_zone: str) -> RecallSettingsResponse:
    return RecallSettingsResponse(
        time_zone=time_zone,
        enabled=s.enabled,
        intensity=s.intensity,
        morning_checkin_enabled=s.morning_checkin_enabled,
        idle_time_enabled=s.idle_time_enabled,
        walking_mode_enabled=s.walking_mode_enabled,
        walking_steps_threshold=s.walking_steps_threshold,
        study_breaks_enabled=s.study_breaks_enabled,
        study_blocks_before_break=s.study_blocks_before_break,
        night_winddown_enabled=s.night_winddown_enabled,
        night_start_time=s.night_start_time,
        night_end_time=s.night_end_time,
        push_enabled=s.push_enabled,
        email_enabled=s.email_enabled,
        desktop_enabled=s.desktop_enabled,
        in_app_enabled=s.in_app_enabled,
        quiet_hours_start=s.quiet_hours_start,
        quiet_hours_end=s.quiet_hours_end,
    )


@router.get("/recall-settings", response_model=RecallSettingsResponse)
def get_recall_settings(current_user: CurrentUser, settings_repo: RecallSettingsRepo) -> RecallSettingsResponse:
    settings = GetRecallSettingsUseCase(settings_repo).execute(current_user.id)
    return _settings_to_response(settings, current_user.time_zone)


@router.put("/recall-settings", response_model=RecallSettingsResponse)
def update_recall_settings(
    payload: RecallSettingsUpdateRequest,
    request: Request,
    current_user: CurrentUser,
    settings_repo: RecallSettingsRepo,
    user_repo: UserRepo,
    reminder_repo: ReminderRepo,
) -> RecallSettingsResponse:
    fields = payload.model_dump()
    # The zone lives on the user, not on RecallSettings, so it is split off
    # before the rest is used to build the settings record.
    requested_zone = fields.pop("time_zone", None)

    updated = RecallSettings(user_id=current_user.id, **fields)
    saved = UpdateRecallSettingsUseCase(settings_repo).execute(current_user.id, updated)

    # Absent outside a running application (unit tests, any caller that
    # starts no scheduler), in which case there are no registered jobs to move.
    running_scheduler = getattr(request.app.state, "scheduler", None)
    jobs = (
        build_reminder_scheduler(
            running_scheduler,
            SessionLocal,
            getattr(request.app.state, "notification_channel", None) or LogNotificationChannel(),
        )
        if running_scheduler is not None
        else None
    )
    time_zone = SetUserTimeZoneUseCase(user_repo, reminder_repo, jobs).execute(
        current_user.id, requested_zone or current_user.time_zone
    )

    return _settings_to_response(saved, time_zone)


@router.get("/profile", response_model=ProfileOverviewResponse)
def get_profile(current_user: CurrentUser, user_repo: UserRepo, word_repo: WordRepo) -> ProfileOverviewResponse:
    from app.api.routers.auth import _to_user_response

    overview = GetProfileOverviewUseCase(user_repo, word_repo).execute(current_user.id)
    earned_codes = {b.code for b in overview.earned_badges}
    badges = [
        BadgeResponse(code=b.code, name=b.name, icon=b.icon, description=b.description, earned=b.code in earned_codes)
        for b in overview.all_badges
    ]
    return ProfileOverviewResponse(user=_to_user_response(overview.user), badges=badges)
