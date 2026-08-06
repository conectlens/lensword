"""Bounded measurable companion activity endpoints (#194)."""
from uuid import uuid4

from fastapi import APIRouter, HTTPException, status

from app.api.deps import CompanionActivityRepo, CompanionSessionRepo, CurrentUser, RecallSettingsRepo
from app.api.schemas.companion import (
    CompanionActivityAnswerRequest,
    CompanionActivityCreateRequest,
    CompanionActivityResponse,
)
from app.domain.services.companion_activities import (
    ActivityStatus,
    ActivityType,
    LearningActivity,
    evaluate_response,
)
from app.domain.services.companion_sessions import CompanionSessionStatus
from app.domain.value_objects import utcnow

router = APIRouter(prefix="/api/v1/companion/sessions", tags=["companion activities"])


def _enabled(settings_repo: RecallSettingsRepo, user_id: int) -> None:
    settings = settings_repo.get_by_user(user_id)
    if not settings or not settings.ai_companion_enabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="AI Companion is not enabled")


def _session(repo: CompanionSessionRepo, user_id: int, session_id: str):
    session = repo.get(user_id, session_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Companion session not found")
    return session


def _response(activity: LearningActivity) -> CompanionActivityResponse:
    return CompanionActivityResponse(
        id=activity.id,
        session_id=activity.session_id,
        activity_type=activity.activity_type.value,
        prompt=activity.prompt,
        expected_evaluation=activity.expected_evaluation,
        status=activity.status.value,
        response=activity.response,
        result=activity.result,
        operation_id=activity.operation_id,
        started_at=activity.started_at,
        updated_at=activity.updated_at,
        revision=activity.revision,
    )


@router.post("/{session_id}/activities", response_model=CompanionActivityResponse, status_code=status.HTTP_201_CREATED)
def begin_activity(
    session_id: str,
    payload: CompanionActivityCreateRequest,
    current_user: CurrentUser,
    settings_repo: RecallSettingsRepo,
    session_repo: CompanionSessionRepo,
    activity_repo: CompanionActivityRepo,
):
    _enabled(settings_repo, current_user.id)
    session = _session(session_repo, current_user.id, session_id)
    if session.status is not CompanionSessionStatus.ACTIVE:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Session is not active")
    try:
        activity_type = ActivityType(payload.activity_type)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unsupported activity type") from exc
    if payload.operation_id:
        existing = activity_repo.find_by_operation(current_user.id, session_id, payload.operation_id)
        if existing is not None:
            return _response(existing)
    now = utcnow()
    try:
        activity = activity_repo.add(
            LearningActivity(
                id=uuid4().hex,
                session_id=session_id,
                user_id=current_user.id,
                activity_type=activity_type,
                prompt=payload.prompt,
                expected_evaluation=payload.expected_evaluation,
                status=ActivityStatus.ACTIVE,
                response=None,
                result=None,
                operation_id=payload.operation_id,
                started_at=now,
                updated_at=now,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return _response(activity)


@router.get("/{session_id}/activities/{activity_id}", response_model=CompanionActivityResponse)
def get_activity(session_id: str, activity_id: str, current_user: CurrentUser, settings_repo: RecallSettingsRepo, session_repo: CompanionSessionRepo, activity_repo: CompanionActivityRepo):
    _enabled(settings_repo, current_user.id)
    _session(session_repo, current_user.id, session_id)
    activity = activity_repo.get(current_user.id, session_id, activity_id)
    if activity is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Activity not found")
    return _response(activity)


@router.post("/{session_id}/activities/{activity_id}/response", response_model=CompanionActivityResponse)
def submit_activity_response(session_id: str, activity_id: str, payload: CompanionActivityAnswerRequest, current_user: CurrentUser, settings_repo: RecallSettingsRepo, session_repo: CompanionSessionRepo, activity_repo: CompanionActivityRepo):
    _enabled(settings_repo, current_user.id)
    _session(session_repo, current_user.id, session_id)
    activity = activity_repo.get(current_user.id, session_id, activity_id)
    if activity is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Activity not found")
    try:
        activity.submit(payload.response, evaluate_response(activity, payload.response))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    activity.updated_at = utcnow()
    return _response(activity_repo.update(activity))


@router.post("/{session_id}/activities/{activity_id}/finish", response_model=CompanionActivityResponse)
def finish_activity(session_id: str, activity_id: str, current_user: CurrentUser, settings_repo: RecallSettingsRepo, session_repo: CompanionSessionRepo, activity_repo: CompanionActivityRepo):
    _enabled(settings_repo, current_user.id)
    _session(session_repo, current_user.id, session_id)
    activity = activity_repo.get(current_user.id, session_id, activity_id)
    if activity is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Activity not found")
    try:
        activity.finish()
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    activity.updated_at = utcnow()
    return _response(activity_repo.update(activity))
