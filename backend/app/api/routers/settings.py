from fastapi import APIRouter

from app.api.deps import CurrentUser, RecallSettingsRepo, UserRepo, WordRepo
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
from app.domain.entities import RecallSettings

router = APIRouter(prefix="/api/v1", tags=["settings"])


def _settings_to_response(s: RecallSettings) -> RecallSettingsResponse:
    return RecallSettingsResponse(
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
    return _settings_to_response(settings)


@router.put("/recall-settings", response_model=RecallSettingsResponse)
def update_recall_settings(
    payload: RecallSettingsUpdateRequest, current_user: CurrentUser, settings_repo: RecallSettingsRepo
) -> RecallSettingsResponse:
    updated = RecallSettings(user_id=current_user.id, **payload.model_dump())
    saved = UpdateRecallSettingsUseCase(settings_repo).execute(current_user.id, updated)
    return _settings_to_response(saved)


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
