"""Durable, provider-neutral companion sessions (#193)."""
import logging
from typing import Callable

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import (
    CompanionSessionRepo,
    CurrentUser,
    PerUserAIProvider,
    RecallSettingsRepo,
    rate_limit_ai,
)
from app.api.schemas.companion import (
    CompanionActionResponse,
    CompanionExportResponse,
    CompanionChatRequest,
    CompanionChatResponse,
    CompanionSessionCreateRequest,
    CompanionSessionResponse,
    CompanionSessionTransferRequest,
    CompanionTurnRequest,
    CompanionTurnResponse,
)
from app.application.use_cases.companion_sessions import (
    FinishCompanionSessionUseCase,
    GetCompanionSessionUseCase,
    StartCompanionSessionUseCase,
    TransitionCompanionSessionUseCase,
    SummarizeCompanionSessionUseCase,
)
from app.domain.exceptions import (
    AIProviderUnavailableError,
    ConcurrentModificationError,
    EntityNotFoundError,
)
from app.domain.services.companion_sessions import (
    CompanionSession,
    CompanionSessionStatus,
    CompanionTurn,
    CompanionTurnRole,
)
from app.domain.services.conversation import (
    Difficulty,
    Speaker,
    Turn,
    build_context,
    validate_reply,
)
from app.domain.value_objects import utcnow

logger = logging.getLogger(__name__)

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
    session = StartCompanionSessionUseCase(session_repo).execute(
        current_user.id,
        connection_id=payload.connection_id,
        client_id=payload.client_id,
        goal=payload.goal,
        language=payload.language,
        group_id=payload.group_id,
        difficulty=payload.difficulty,
        active_activity=payload.active_activity,
        consent_snapshot=payload.consent_snapshot,
    )
    return _session_response(session_repo, session)


@router.get("/{session_id}", response_model=CompanionSessionResponse)
def get_session(session_id: str, current_user: CurrentUser, settings_repo: RecallSettingsRepo, session_repo: CompanionSessionRepo):
    _require_enabled(settings_repo, current_user.id)
    try:
        session = GetCompanionSessionUseCase(session_repo).execute(current_user.id, session_id)
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Companion session not found") from exc
    return _session_response(session_repo, session)


def _apply(
    session_id: str,
    current_user: CurrentUser,
    settings_repo: RecallSettingsRepo,
    session_repo: CompanionSessionRepo,
    mutate: Callable[[CompanionSession], None],
) -> CompanionSession:
    """Read-mutate-write through TransitionCompanionSessionUseCase, with real
    optimistic locking (#193 TODO 3): a revision that moved underneath us —
    another request won the race — raises ConcurrentModificationError,
    translated to 409 here rather than silently overwritten. An invalid
    transition (e.g. resuming a revoked session) raises ValueError from the
    domain object itself, also a 409: both are "the request cannot be
    applied to the session as it currently is", distinguished by detail text
    rather than by status code.
    """
    _require_enabled(settings_repo, current_user.id)
    try:
        return TransitionCompanionSessionUseCase(session_repo).execute(current_user.id, session_id, mutate)
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Companion session not found") from exc
    except (ValueError, ConcurrentModificationError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


def _action(session_id: str, current_user, settings_repo, session_repo, action: str) -> CompanionActionResponse:
    session = _apply(session_id, current_user, settings_repo, session_repo, lambda s: getattr(s, action)())
    return CompanionActionResponse(session=_session_response(session_repo, session))


@router.post("/{session_id}/resume", response_model=CompanionActionResponse)
def resume_session(session_id: str, current_user: CurrentUser, settings_repo: RecallSettingsRepo, session_repo: CompanionSessionRepo):
    return _action(session_id, current_user, settings_repo, session_repo, "resume")


@router.post("/{session_id}/pause", response_model=CompanionActionResponse)
def pause_session(session_id: str, current_user: CurrentUser, settings_repo: RecallSettingsRepo, session_repo: CompanionSessionRepo):
    return _action(session_id, current_user, settings_repo, session_repo, "pause")


@router.post("/{session_id}/finish", response_model=CompanionActionResponse)
async def finish_session(
    session_id: str,
    current_user: CurrentUser,
    settings_repo: RecallSettingsRepo,
    session_repo: CompanionSessionRepo,
    provider: PerUserAIProvider,
):
    """Finishing is the natural point to summarize (#193 TODO 2) — see
    FinishCompanionSessionUseCase, shared with the MCP `finish_companion_session`
    tool so both surfaces summarize identically."""
    _require_enabled(settings_repo, current_user.id)
    try:
        session = await FinishCompanionSessionUseCase(session_repo, provider).execute(current_user.id, session_id)
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Companion session not found") from exc
    except (ValueError, ConcurrentModificationError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return CompanionActionResponse(session=_session_response(session_repo, session))


@router.post("/{session_id}/summary", response_model=CompanionActionResponse)
async def regenerate_summary(
    session_id: str,
    current_user: CurrentUser,
    settings_repo: RecallSettingsRepo,
    session_repo: CompanionSessionRepo,
    provider: PerUserAIProvider,
):
    """Regenerate the summary on demand — e.g. a resuming client wants a
    fresh recap mid-session without ending it. Always available even with no
    AI provider configured: the deterministic fallback is the whole point of
    #193 TODO 2, not just what happens when the AI path fails."""
    _require_enabled(settings_repo, current_user.id)
    session = _owned(session_repo, current_user.id, session_id)
    summary, _source = await SummarizeCompanionSessionUseCase(session_repo, provider).build_summary(session)
    session = _apply(
        session_id, current_user, settings_repo, session_repo, lambda s: s.update_summary(summary)
    )
    return CompanionActionResponse(session=_session_response(session_repo, session))


@router.post("/{session_id}/revoke", response_model=CompanionActionResponse)
def revoke_session(session_id: str, current_user: CurrentUser, settings_repo: RecallSettingsRepo, session_repo: CompanionSessionRepo):
    return _action(session_id, current_user, settings_repo, session_repo, "revoke")


@router.post("/{session_id}/transfer", response_model=CompanionActionResponse)
def transfer_session(
    session_id: str,
    payload: CompanionSessionTransferRequest,
    current_user: CurrentUser,
    settings_repo: RecallSettingsRepo,
    session_repo: CompanionSessionRepo,
):
    """Reassign control of a session to a different companion connection
    (#193 TODO 3) — e.g. continuing on a phone what was started on a
    desktop. Owner-authorized like every other action here: the caller's
    bearer token already proves it is their session regardless of which
    connection currently controls it, so no separate check is needed."""
    session = _apply(
        session_id,
        current_user,
        settings_repo,
        session_repo,
        lambda s: s.transfer(payload.connection_id, payload.client_id),
    )
    return CompanionActionResponse(session=_session_response(session_repo, session))


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


def _difficulty_of(value: str | None) -> Difficulty:
    try:
        return Difficulty(value)
    except ValueError:
        # Stored as a free-form string, so an unrecognised value is a data
        # possibility rather than a programming error.
        return Difficulty.STEADY


def _turn_response(turn: CompanionTurn) -> CompanionTurnResponse:
    return CompanionTurnResponse(
        id=turn.id,
        session_id=turn.session_id,
        role=turn.role,
        content=turn.content,
        activity_id=turn.activity_id,
        operation_id=turn.operation_id,
        created_at=turn.created_at,
    )


def _record(session_repo, session_id: str, role: CompanionTurnRole, content: str, operation_id: str | None) -> CompanionTurn:
    return session_repo.add_turn(
        CompanionTurn(
            id=None,
            session_id=session_id,
            role=role,
            content=content,
            activity_id=None,
            operation_id=operation_id,
            created_at=utcnow(),
        )
    )


@router.post("/{session_id}/chat", response_model=CompanionChatResponse, dependencies=[Depends(rate_limit_ai)])
async def chat(
    session_id: str,
    payload: CompanionChatRequest,
    current_user: CurrentUser,
    settings_repo: RecallSettingsRepo,
    session_repo: CompanionSessionRepo,
    provider: PerUserAIProvider,
) -> CompanionChatResponse:
    """Answer one in-app chat message inside an existing companion session.

    `POST /turns` exists for an external companion that has already produced
    a turn elsewhere. An in-app chat has no such external author, so this
    endpoint owns both halves of the exchange — while still writing them as
    ordinary companion turns, so a conversation started in the app stays
    readable, exportable and resumable through every other companion route.

    The user's turn is stored *before* the provider is called. A model that
    is down then costs the answer, not what the person typed.
    """
    _require_enabled(settings_repo, current_user.id)
    session = _owned(session_repo, current_user.id, session_id)
    if session.status is not CompanionSessionStatus.ACTIVE:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Session is not active")

    # A retried request must not produce a second copy of the exchange. The
    # assistant half is keyed off the same id so both halves are recoverable
    # together rather than the reply being regenerated against a turn that
    # was already stored.
    assistant_operation_id = f"{payload.operation_id}:assistant" if payload.operation_id else None
    if payload.operation_id:
        existing = session_repo.find_turn_by_operation(current_user.id, session_id, payload.operation_id)
        if existing is not None:
            answered = session_repo.find_turn_by_operation(current_user.id, session_id, assistant_operation_id)
            return CompanionChatResponse(
                status="ok" if answered else "unavailable",
                user_turn=_turn_response(existing),
                assistant_turn=_turn_response(answered) if answered else None,
                detail=None if answered else "The previous attempt was not answered. Send again to retry.",
            )

    history = [
        Turn(
            speaker=Speaker.LEARNER if turn.role is CompanionTurnRole.USER else Speaker.TUTOR,
            text=turn.content,
        )
        for turn in session_repo.list_turns(current_user.id, session_id)
    ]

    try:
        user_turn = _record(session_repo, session_id, CompanionTurnRole.USER, payload.content, payload.operation_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    if provider is None:
        return CompanionChatResponse(
            status="disabled",
            user_turn=_turn_response(user_turn),
            detail="AI is not configured for this deployment, so the companion cannot reply.",
        )

    context = build_context(
        target_language=session.language or "English",
        difficulty=_difficulty_of(session.difficulty),
        scenario=session.goal,
        # The session's own transcript, injected as data and never as
        # instructions — a companion turn is user-supplied text.
        vocabulary=[],
        recent_mistakes=[],
        history=history,
    )

    try:
        raw = await provider.converse(context, payload.content)
    except AIProviderUnavailableError as exc:
        return CompanionChatResponse(status="unavailable", user_turn=_turn_response(user_turn), detail=str(exc))

    try:
        answer, _corrections = validate_reply(raw, payload.content)
    except ValueError as exc:
        logger.info("Companion reply rejected: %s", exc)
        return CompanionChatResponse(status="unavailable", user_turn=_turn_response(user_turn), detail=str(exc))

    assistant_turn = _record(session_repo, session_id, CompanionTurnRole.ASSISTANT, answer, assistant_operation_id)
    return CompanionChatResponse(
        status="ok",
        user_turn=_turn_response(user_turn),
        assistant_turn=_turn_response(assistant_turn),
    )
