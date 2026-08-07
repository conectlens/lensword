"""Bounded measurable companion activity endpoints (#194)."""
from uuid import uuid4

from fastapi import APIRouter, HTTPException, status

from app.api.deps import (
    CompanionActivityRepo,
    CompanionSessionRepo,
    CurrentUser,
    DiagnosisRepo,
    GroupRepo,
    LearningObservationRepo,
    RecallSettingsRepo,
    WordRepo,
)
from app.api.schemas.companion import (
    CompanionActivityAnswerRequest,
    CompanionActivityCreateRequest,
    CompanionActivityEvidenceResponse,
    CompanionActivityHintResponse,
    CompanionActivityResponse,
)
from app.application.use_cases.companion_activities import (
    BeginLearningActivityUseCase,
    ExplainActivityEvidenceUseCase,
    RequestActivityHintUseCase,
    SubmitActivityResponseUseCase,
)
from app.domain.exceptions import EntityNotFoundError, PermissionDeniedError, ValidationError
from app.domain.services.companion_activities import (
    MAX_HINTS_PER_ACTIVITY,
    ActivityStatus,
    ActivityType,
    LearningActivity,
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
        hints_used=activity.hints_used,
    )


def _activity(activity_repo: CompanionActivityRepo, user_id: int, session_id: str, activity_id: str) -> LearningActivity:
    activity = activity_repo.get(user_id, session_id, activity_id)
    if activity is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Activity not found")
    return activity


@router.post("/{session_id}/activities", response_model=CompanionActivityResponse, status_code=status.HTTP_201_CREATED)
def begin_activity(
    session_id: str,
    payload: CompanionActivityCreateRequest,
    current_user: CurrentUser,
    settings_repo: RecallSettingsRepo,
    session_repo: CompanionSessionRepo,
    activity_repo: CompanionActivityRepo,
    word_repo: WordRepo,
    group_repo: GroupRepo,
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
    # The evaluation rule is validated and fixed here, once, before the
    # activity is ever persisted (#194 TODO 5): nothing downstream can
    # change `expected_evaluation` after this point.
    try:
        BeginLearningActivityUseCase(word_repo, group_repo).validate(
            current_user.id, activity_type, payload.expected_evaluation
        )
    except (EntityNotFoundError, PermissionDeniedError) as exc:
        # 404 for both "no such word" and "someone else's word" — the same
        # existence-disclosure posture app.api.routers.interventions'
        # `_require_owned_word` already uses for word ownership checks.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Word not found") from exc
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
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
    activity = _activity(activity_repo, current_user.id, session_id, activity_id)
    return _response(activity)


@router.post("/{session_id}/activities/{activity_id}/response", response_model=CompanionActivityResponse)
def submit_activity_response(
    session_id: str,
    activity_id: str,
    payload: CompanionActivityAnswerRequest,
    current_user: CurrentUser,
    settings_repo: RecallSettingsRepo,
    session_repo: CompanionSessionRepo,
    activity_repo: CompanionActivityRepo,
    observation_repo: LearningObservationRepo,
):
    _enabled(settings_repo, current_user.id)
    _session(session_repo, current_user.id, session_id)
    activity = _activity(activity_repo, current_user.id, session_id, activity_id)
    try:
        result = SubmitActivityResponseUseCase(activity_repo, observation_repo).execute(
            current_user.id, activity, payload.response
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _response(result.activity)


@router.post("/{session_id}/activities/{activity_id}/finish", response_model=CompanionActivityResponse)
def finish_activity(session_id: str, activity_id: str, current_user: CurrentUser, settings_repo: RecallSettingsRepo, session_repo: CompanionSessionRepo, activity_repo: CompanionActivityRepo):
    _enabled(settings_repo, current_user.id)
    _session(session_repo, current_user.id, session_id)
    activity = _activity(activity_repo, current_user.id, session_id, activity_id)
    try:
        activity.finish()
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    activity.updated_at = utcnow()
    return _response(activity_repo.update(activity))


@router.post("/{session_id}/activities/{activity_id}/cancel", response_model=CompanionActivityResponse)
def cancel_activity(session_id: str, activity_id: str, current_user: CurrentUser, settings_repo: RecallSettingsRepo, session_repo: CompanionSessionRepo, activity_repo: CompanionActivityRepo):
    _enabled(settings_repo, current_user.id)
    _session(session_repo, current_user.id, session_id)
    activity = _activity(activity_repo, current_user.id, session_id, activity_id)
    try:
        activity.cancel()
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    activity.updated_at = utcnow()
    return _response(activity_repo.update(activity))


@router.post("/{session_id}/activities/{activity_id}/hint", response_model=CompanionActivityHintResponse)
def request_hint(
    session_id: str,
    activity_id: str,
    current_user: CurrentUser,
    settings_repo: RecallSettingsRepo,
    session_repo: CompanionSessionRepo,
    activity_repo: CompanionActivityRepo,
    word_repo: WordRepo,
    group_repo: GroupRepo,
):
    """#194 TODO 1's `request_hint` tool, exposed over REST."""
    _enabled(settings_repo, current_user.id)
    _session(session_repo, current_user.id, session_id)
    activity = _activity(activity_repo, current_user.id, session_id, activity_id)
    try:
        updated, hint = RequestActivityHintUseCase(activity_repo, word_repo, group_repo).execute(current_user.id, activity)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return CompanionActivityHintResponse(
        activity=_response(updated),
        hint=hint,
        hints_used=updated.hints_used,
        hints_remaining=max(0, MAX_HINTS_PER_ACTIVITY - updated.hints_used),
    )


@router.get("/{session_id}/activities/{activity_id}/evidence", response_model=CompanionActivityEvidenceResponse)
def explain_evidence(
    session_id: str,
    activity_id: str,
    current_user: CurrentUser,
    settings_repo: RecallSettingsRepo,
    session_repo: CompanionSessionRepo,
    activity_repo: CompanionActivityRepo,
    word_repo: WordRepo,
    group_repo: GroupRepo,
    diagnosis_repo: DiagnosisRepo,
):
    """#194 TODO 1's `explain_evidence` tool, exposed over REST — a
    deterministic explanation of why this activity was scored the way it
    was, grounded in the same evidence `ExplainWordForUserUseCase` (#185)
    already surfaces for a word, never an AI call."""
    _enabled(settings_repo, current_user.id)
    _session(session_repo, current_user.id, session_id)
    activity = _activity(activity_repo, current_user.id, session_id, activity_id)
    evidence = ExplainActivityEvidenceUseCase(word_repo, group_repo, diagnosis_repo).execute(current_user.id, activity)
    return CompanionActivityEvidenceResponse(**evidence)
