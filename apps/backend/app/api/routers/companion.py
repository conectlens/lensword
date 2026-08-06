"""Durable, provider-neutral companion sessions (#193)."""
from uuid import uuid4

from fastapi import APIRouter, HTTPException, status

from app.api.deps import CompanionSessionRepo, CurrentUser, RecallSettingsRepo
from app.api.schemas.companion import (
    CompanionActionResponse,
    CompanionExportResponse,
    CompanionSessionCreateRequest,
    CompanionSessionResponse,
    CompanionTurnRequest,
    CompanionTurnResponse,
)
from app.domain.services.companion_sessions import CompanionSession, CompanionSessionStatus, CompanionTurn
from app.domain.value_objects import utcnow

router = APIRouter(prefix="/api/v1/companion/sessions", tags=["companion"])


def _require_enabled(settings_repo: RecallSettingsRepo, user_id: int) -> None:
    settings = settings_repo.get_by_user(user_id)
    if not settings or not settings.ai_companion_enabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="AI Companion is not enabled")


def _session_response(repo: CompanionSessionRepo, session: CompanionSession) -> CompanionSessionResponse:
    return CompanionSessionResponse(
        id=session.id,
        connection_id=session.connection_id,
        client_id=session.client_id,
        goal=session.goal,
        language=session.language,
        group_id=session.group_id,
        difficulty=session.difficulty,
        active_activity=session.active_activity,
        consent_snapshot=session.consent_snapshot,
        summary=session.summary,
        status=session.status,
        revision=session.revision,
        created_at=session.created_at,
        updated_at=session.updated_at,
        turns=[
            CompanionTurnResponse(
                id=turn.id,
                session_id=turn.session_id,
                role=turn.role,
                content=turn.content,
                activity_id=turn.activity_id,
                operation_id=turn.operation_id,
                created_at=turn.created_at,
            )
            for turn in repo.list_turns(session.user_id, session.id)
        ],
    )


def _owned(repo: CompanionSessionRepo, user_id: int, session_id: str) -> CompanionSession:
    session = repo.get(user_id, session_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Companion session not found")
    return session


@router.post("", response_model=CompanionSessionResponse, status_code=status.HTTP_201_CREATED)
def start_session(
    payload: CompanionSessionCreateRequest,
    current_user: CurrentUser,
    settings_repo: RecallSettingsRepo,
    session_repo: CompanionSessionRepo,
) -> CompanionSessionResponse:
    _require_enabled(settings_repo, current_user.id)
    now = utcnow()
    session = session_repo.add(
        CompanionSession(
            id=uuid4().hex,
            user_id=current_user.id,
            connection_id=payload.connection_id,
            client_id=payload.client_id,
            goal=payload.goal,
            language=payload.language,
            group_id=payload.group_id,
            difficulty=payload.difficulty,
            active_activity=payload.active_activity,
            consent_snapshot=payload.consent_snapshot,
            summary=None,
            status=CompanionSessionStatus.ACTIVE,
            revision=1,
            created_at=now,
            updated_at=now,
        )
    )
    return _session_response(session_repo, session)


@router.get("/{session_id}", response_model=CompanionSessionResponse)
def get_session(session_id: str, current_user: CurrentUser, settings_repo: RecallSettingsRepo, session_repo: CompanionSessionRepo):
    _require_enabled(settings_repo, current_user.id)
    return _session_response(session_repo, _owned(session_repo, current_user.id, session_id))


def _action(session_id: str, current_user, settings_repo, session_repo, action: str) -> CompanionActionResponse:
    _require_enabled(settings_repo, current_user.id)
    session = _owned(session_repo, current_user.id, session_id)
    try:
        getattr(session, action)()
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    session.updated_at = utcnow()
    session = session_repo.update(session)
    return CompanionActionResponse(session=_session_response(session_repo, session))


@router.post("/{session_id}/resume", response_model=CompanionActionResponse)
def resume_session(session_id: str, current_user: CurrentUser, settings_repo: RecallSettingsRepo, session_repo: CompanionSessionRepo):
    return _action(session_id, current_user, settings_repo, session_repo, "resume")


@router.post("/{session_id}/pause", response_model=CompanionActionResponse)
def pause_session(session_id: str, current_user: CurrentUser, settings_repo: RecallSettingsRepo, session_repo: CompanionSessionRepo):
    return _action(session_id, current_user, settings_repo, session_repo, "pause")


@router.post("/{session_id}/finish", response_model=CompanionActionResponse)
def finish_session(session_id: str, current_user: CurrentUser, settings_repo: RecallSettingsRepo, session_repo: CompanionSessionRepo):
    return _action(session_id, current_user, settings_repo, session_repo, "finish")


@router.post("/{session_id}/revoke", response_model=CompanionActionResponse)
def revoke_session(session_id: str, current_user: CurrentUser, settings_repo: RecallSettingsRepo, session_repo: CompanionSessionRepo):
    return _action(session_id, current_user, settings_repo, session_repo, "revoke")


@router.post("/{session_id}/turns", response_model=CompanionTurnResponse, status_code=status.HTTP_201_CREATED)
def add_turn(
    session_id: str,
    payload: CompanionTurnRequest,
    current_user: CurrentUser,
    settings_repo: RecallSettingsRepo,
    session_repo: CompanionSessionRepo,
) -> CompanionTurnResponse:
    _require_enabled(settings_repo, current_user.id)
    session = _owned(session_repo, current_user.id, session_id)
    if session.status is not CompanionSessionStatus.ACTIVE:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Session is not active")
    if payload.operation_id:
        existing = session_repo.find_turn_by_operation(current_user.id, session_id, payload.operation_id)
        if existing is not None:
            return CompanionTurnResponse(
                id=existing.id,
                session_id=existing.session_id,
                role=existing.role,
                content=existing.content,
                activity_id=existing.activity_id,
                operation_id=existing.operation_id,
                created_at=existing.created_at,
            )
    try:
        turn = session_repo.add_turn(
            CompanionTurn(
                id=None,
                session_id=session_id,
                role=payload.role,
                content=payload.content,
                activity_id=payload.activity_id,
                operation_id=payload.operation_id,
                created_at=utcnow(),
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return CompanionTurnResponse(
        id=turn.id,
        session_id=turn.session_id,
        role=turn.role,
        content=turn.content,
        activity_id=turn.activity_id,
        operation_id=turn.operation_id,
        created_at=turn.created_at,
    )


@router.get("/{session_id}/export", response_model=CompanionExportResponse)
def export_session(session_id: str, current_user: CurrentUser, settings_repo: RecallSettingsRepo, session_repo: CompanionSessionRepo):
    _require_enabled(settings_repo, current_user.id)
    return CompanionExportResponse(session=_session_response(session_repo, _owned(session_repo, current_user.id, session_id)))


@router.delete("/{session_id}/content", status_code=status.HTTP_204_NO_CONTENT)
def delete_content(session_id: str, current_user: CurrentUser, settings_repo: RecallSettingsRepo, session_repo: CompanionSessionRepo):
    _require_enabled(settings_repo, current_user.id)
    _owned(session_repo, current_user.id, session_id)
    session_repo.delete_content(current_user.id, session_id)
