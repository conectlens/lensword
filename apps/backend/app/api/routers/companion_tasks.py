"""Capability-gated durable companion tasks (#197)."""
from datetime import timedelta
from uuid import uuid4

from fastapi import APIRouter, HTTPException, status

from app.api.deps import CompanionSessionRepo, CompanionTaskRepo, CurrentUser, RecallSettingsRepo
from app.api.schemas.companion import (
    CompanionTaskCompleteRequest,
    CompanionTaskCreateRequest,
    CompanionTaskProgressRequest,
    CompanionTaskResponse,
)
from app.domain.services.companion_sessions import CompanionSessionStatus
from app.domain.services.companion_tasks import CompanionTask, CompanionTaskStatus, CompanionTaskType
from app.domain.value_objects import utcnow

router = APIRouter(prefix="/api/v1/companion/sessions", tags=["companion tasks"])


def _enabled(settings_repo: RecallSettingsRepo, user_id: int) -> None:
    settings = settings_repo.get_by_user(user_id)
    if not settings or not settings.ai_companion_enabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="AI Companion is not enabled")


def _session(session_repo: CompanionSessionRepo, user_id: int, session_id: str):
    session = session_repo.get(user_id, session_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Companion session not found")
    return session


def _response(task: CompanionTask) -> CompanionTaskResponse:
    return CompanionTaskResponse(
        id=task.id,
        session_id=task.session_id,
        task_type=task.task_type.value,
        status=task.status.value,
        total_units=task.total_units,
        completed_units=task.completed_units,
        progress=task.progress,
        result=task.result,
        error=task.error,
        operation_id=task.operation_id,
        expires_at=task.expires_at,
        created_at=task.created_at,
        updated_at=task.updated_at,
        revision=task.revision,
        input=task.input,
    )


def _task(task_repo: CompanionTaskRepo, user_id: int, session_id: str, task_id: str) -> CompanionTask:
    task = task_repo.get(user_id, session_id, task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Companion task not found")
    if task.expire_if_due(utcnow()):
        task = task_repo.update(task)
    return task


@router.post("/{session_id}/tasks", response_model=CompanionTaskResponse, status_code=status.HTTP_201_CREATED)
def create_task(
    session_id: str,
    payload: CompanionTaskCreateRequest,
    current_user: CurrentUser,
    settings_repo: RecallSettingsRepo,
    session_repo: CompanionSessionRepo,
    task_repo: CompanionTaskRepo,
):
    _enabled(settings_repo, current_user.id)
    session = _session(session_repo, current_user.id, session_id)
    if session.status is not CompanionSessionStatus.ACTIVE:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Session is not active")
    try:
        task_type = CompanionTaskType(payload.task_type)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unsupported task type") from exc
    if payload.operation_id:
        existing = task_repo.find_by_operation(current_user.id, session_id, payload.operation_id)
        if existing is not None:
            return _response(existing)
    now = utcnow()
    try:
        task = task_repo.add(
            CompanionTask(
                id=uuid4().hex,
                session_id=session_id,
                user_id=current_user.id,
                task_type=task_type,
                status=CompanionTaskStatus.PENDING,
                total_units=payload.total_units,
                completed_units=0,
                result=None,
                error=None,
                operation_id=payload.operation_id,
                expires_at=now + timedelta(seconds=payload.expires_in_seconds),
                created_at=now,
                updated_at=now,
                input=payload.input,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return _response(task)


@router.get("/{session_id}/tasks", response_model=list[CompanionTaskResponse])
def list_tasks(
    session_id: str,
    current_user: CurrentUser,
    settings_repo: RecallSettingsRepo,
    session_repo: CompanionSessionRepo,
    task_repo: CompanionTaskRepo,
):
    _enabled(settings_repo, current_user.id)
    _session(session_repo, current_user.id, session_id)
    return [_response(_task(task_repo, current_user.id, session_id, task.id)) for task in task_repo.list_for_session(current_user.id, session_id)]


@router.get("/{session_id}/tasks/{task_id}", response_model=CompanionTaskResponse)
def get_task(
    session_id: str,
    task_id: str,
    current_user: CurrentUser,
    settings_repo: RecallSettingsRepo,
    session_repo: CompanionSessionRepo,
    task_repo: CompanionTaskRepo,
):
    _enabled(settings_repo, current_user.id)
    _session(session_repo, current_user.id, session_id)
    return _response(_task(task_repo, current_user.id, session_id, task_id))


def _mutate(
    session_id: str,
    task_id: str,
    current_user,
    settings_repo,
    session_repo,
    task_repo,
    operation,
):
    _enabled(settings_repo, current_user.id)
    _session(session_repo, current_user.id, session_id)
    task = _task(task_repo, current_user.id, session_id, task_id)
    try:
        operation(task)
        return _response(task_repo.update(task))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/{session_id}/tasks/{task_id}/start", response_model=CompanionTaskResponse)
def start_task(session_id: str, task_id: str, current_user: CurrentUser, settings_repo: RecallSettingsRepo, session_repo: CompanionSessionRepo, task_repo: CompanionTaskRepo):
    return _mutate(session_id, task_id, current_user, settings_repo, session_repo, task_repo, lambda task: task.start(utcnow()))


@router.post("/{session_id}/tasks/{task_id}/progress", response_model=CompanionTaskResponse)
def update_task_progress(session_id: str, task_id: str, payload: CompanionTaskProgressRequest, current_user: CurrentUser, settings_repo: RecallSettingsRepo, session_repo: CompanionSessionRepo, task_repo: CompanionTaskRepo):
    return _mutate(session_id, task_id, current_user, settings_repo, session_repo, task_repo, lambda task: task.update_progress(payload.completed_units, utcnow()))


@router.post("/{session_id}/tasks/{task_id}/complete", response_model=CompanionTaskResponse)
def complete_task(session_id: str, task_id: str, payload: CompanionTaskCompleteRequest, current_user: CurrentUser, settings_repo: RecallSettingsRepo, session_repo: CompanionSessionRepo, task_repo: CompanionTaskRepo):
    return _mutate(session_id, task_id, current_user, settings_repo, session_repo, task_repo, lambda task: task.complete(payload.result, utcnow()))


@router.post("/{session_id}/tasks/{task_id}/cancel", response_model=CompanionTaskResponse)
def cancel_task(session_id: str, task_id: str, current_user: CurrentUser, settings_repo: RecallSettingsRepo, session_repo: CompanionSessionRepo, task_repo: CompanionTaskRepo):
    return _mutate(session_id, task_id, current_user, settings_repo, session_repo, task_repo, lambda task: task.cancel(utcnow()))
