"""Backend half of issue #195 (client sampling, elicitation, bounded loops).

`apps/mcp` has no database of its own — it talks to this backend over HTTP
via `BackendClient`, the same as `context_import.py`/`cli.py` already do for
other bounded workflows. This router is that HTTP surface for the three
pieces of #195 that must be durable/queryable rather than in-process:

* a persisted `CompanionLoopState` budget (TODO 2), so a bounded workflow
  spanning multiple MCP tool calls cannot restart its budget by the MCP
  process restarting;
* a hash-chained sampling provenance record (TODO 4), reusing
  `mcp_policy.redact_and_chain` rather than a second redaction scheme;
* the local-AI/deterministic fallback content path (TODO 0) that #187's
  `companion_coach` module already defines but nothing had wired up yet.

Client `sampling/createMessage` and `elicitation/create` themselves are not
here — only the MCP host the learner is connected to can answer those, and
this backend has no connection to it. That part lives entirely in
`apps/mcp/lensword_mcp/server.py`.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.api.deps import (
    CompanionLoopStateRepo,
    CompanionSamplingEventRepo,
    CompanionSessionRepo,
    CurrentUser,
    OptionalAIProvider,
    RecallSettingsRepo,
)
from app.api.schemas.companion import (
    CompanionLoopReserveRequest,
    CompanionLoopStartRequest,
    CompanionLoopStateResponse,
    CompanionLoopStopRequest,
    CompanionReplyRequest,
    CompanionReplyResponse,
    CompanionSamplingEventCreateRequest,
    CompanionSamplingEventResponse,
)
from app.domain.services.companion_coach import (
    CoachContentRejected,
    CoachEvidence,
    CoachRequest,
    build_coach_prompt,
    deterministic_fallback,
    validate_generated_content,
)
from app.domain.services.companion_loop import CompanionLoopBudget, CompanionLoopState, LoopLimitReached, LoopStopReason
from app.domain.services.companion_sampling_audit import CompanionSamplingEvent, SamplingFallbackPath
from app.domain.services.mcp_policy import redact_and_chain
from app.domain.value_objects import utcnow

router = APIRouter(prefix="/api/v1/companion/sessions", tags=["companion sampling"])


def _enabled(settings_repo: RecallSettingsRepo, user_id: int) -> None:
    settings = settings_repo.get_by_user(user_id)
    if not settings or not settings.ai_companion_enabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="AI Companion is not enabled")


def _owned(session_repo: CompanionSessionRepo, user_id: int, session_id: str) -> None:
    if session_repo.get(user_id, session_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Companion session not found")


def _loop_response(state: CompanionLoopState) -> CompanionLoopStateResponse:
    return CompanionLoopStateResponse(
        session_id=state.session_id,
        tool_calls=state.tool_calls,
        samples=state.samples,
        generated_tokens=state.generated_tokens,
        activities=state.activities,
        writes=state.writes,
        consecutive_failures=state.consecutive_failures,
        stopped_reason=state.stopped_reason,
        started_at=state.started_at,
        updated_at=state.updated_at,
        revision=state.revision,
    )


# --- Bounded companion loop budgets (#195 TODO 2) --------------------------


@router.post("/{session_id}/loop/start", response_model=CompanionLoopStateResponse, status_code=status.HTTP_201_CREATED)
def start_loop(
    session_id: str,
    current_user: CurrentUser,
    settings_repo: RecallSettingsRepo,
    session_repo: CompanionSessionRepo,
    loop_repo: CompanionLoopStateRepo,
    payload: CompanionLoopStartRequest | None = None,
):
    # Every field has a conservative default, so an absent/empty body (a
    # bare "start a bounded loop with the default budget") is valid, not a
    # 422 - it is not a caller error not to override the defaults.
    payload = payload or CompanionLoopStartRequest()
    _enabled(settings_repo, current_user.id)
    _owned(session_repo, current_user.id, session_id)
    now = utcnow()
    try:
        state = CompanionLoopState(
            session_id=session_id,
            user_id=current_user.id,
            budget=CompanionLoopBudget(
                tool_calls=payload.tool_calls,
                samples=payload.samples,
                elapsed_seconds=payload.elapsed_seconds,
                generated_tokens=payload.generated_tokens,
                activities=payload.activities,
                writes=payload.writes,
            ),
            started_at=now,
            updated_at=now,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return _loop_response(loop_repo.start(state))


@router.get("/{session_id}/loop", response_model=CompanionLoopStateResponse)
def get_loop(
    session_id: str,
    current_user: CurrentUser,
    settings_repo: RecallSettingsRepo,
    session_repo: CompanionSessionRepo,
    loop_repo: CompanionLoopStateRepo,
):
    _enabled(settings_repo, current_user.id)
    _owned(session_repo, current_user.id, session_id)
    state = loop_repo.get(current_user.id, session_id)
    if state is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Companion loop has not been started")
    return _loop_response(state)


def _loaded_loop(loop_repo: CompanionLoopStateRepo, user_id: int, session_id: str) -> CompanionLoopState:
    state = loop_repo.get(user_id, session_id)
    if state is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Companion loop has not been started")
    return state


@router.post("/{session_id}/loop/reserve", response_model=CompanionLoopStateResponse)
def reserve_loop(
    session_id: str,
    payload: CompanionLoopReserveRequest,
    current_user: CurrentUser,
    settings_repo: RecallSettingsRepo,
    session_repo: CompanionSessionRepo,
    loop_repo: CompanionLoopStateRepo,
):
    _enabled(settings_repo, current_user.id)
    _owned(session_repo, current_user.id, session_id)
    state = _loaded_loop(loop_repo, current_user.id, session_id)
    try:
        state.reserve(payload.kind, payload.amount, now=utcnow())
    except LoopLimitReached as exc:
        loop_repo.update(state)
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return _loop_response(loop_repo.update(state))


@router.post("/{session_id}/loop/fail", response_model=CompanionLoopStateResponse)
def fail_loop(
    session_id: str,
    current_user: CurrentUser,
    settings_repo: RecallSettingsRepo,
    session_repo: CompanionSessionRepo,
    loop_repo: CompanionLoopStateRepo,
):
    """Record one failed external call. Repeated failure is itself an
    explicit stop condition (#195 TODO 2), independent of the numeric
    budgets `reserve` enforces."""
    _enabled(settings_repo, current_user.id)
    _owned(session_repo, current_user.id, session_id)
    state = _loaded_loop(loop_repo, current_user.id, session_id)
    state.record_failure(utcnow())
    return _loop_response(loop_repo.update(state))


@router.post("/{session_id}/loop/stop", response_model=CompanionLoopStateResponse)
def stop_loop(
    session_id: str,
    payload: CompanionLoopStopRequest,
    current_user: CurrentUser,
    settings_repo: RecallSettingsRepo,
    session_repo: CompanionSessionRepo,
    loop_repo: CompanionLoopStateRepo,
):
    _enabled(settings_repo, current_user.id)
    _owned(session_repo, current_user.id, session_id)
    state = _loaded_loop(loop_repo, current_user.id, session_id)
    try:
        state.stop(LoopStopReason(payload.reason), utcnow())
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return _loop_response(loop_repo.update(state))


# --- Sampling provenance/audit (#195 TODO 4) --------------------------------


@router.post("/{session_id}/sampling-events", response_model=CompanionSamplingEventResponse, status_code=status.HTTP_201_CREATED)
def record_sampling_event(
    session_id: str,
    payload: CompanionSamplingEventCreateRequest,
    current_user: CurrentUser,
    settings_repo: RecallSettingsRepo,
    session_repo: CompanionSessionRepo,
    event_repo: CompanionSamplingEventRepo,
):
    _enabled(settings_repo, current_user.id)
    _owned(session_repo, current_user.id, session_id)
    try:
        fallback_path = SamplingFallbackPath(payload.fallback_path)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unsupported fallback_path") from exc
    previous_hash = event_repo.latest_hash() or "0" * 64
    # Redact defensively even though the payload should already carry only a
    # reference (never a raw prompt/fact) — the same guard `mcp.py`'s audit
    # write applies to tool payloads, reused rather than reimplemented.
    redacted, event_hash = redact_and_chain(
        previous_hash,
        {
            "session_id": session_id,
            "requester": payload.requester,
            "host_client_id": payload.host_client_id,
            "model": payload.model,
            "prompt_template_version": payload.prompt_template_version,
            "source_facts_ref": payload.source_facts_ref,
            "validation_result": payload.validation_result,
            "fallback_path": fallback_path.value,
        },
    )
    try:
        event = event_repo.add(
            CompanionSamplingEvent(
                id=None,
                session_id=session_id,
                user_id=current_user.id,
                requester=redacted["requester"],
                host_client_id=redacted["host_client_id"],
                model=redacted["model"],
                prompt_template_version=redacted["prompt_template_version"],
                source_facts_ref=redacted["source_facts_ref"],
                validation_result=redacted["validation_result"],
                fallback_path=fallback_path,
                previous_hash=previous_hash,
                event_hash=event_hash,
                created_at=utcnow(),
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return CompanionSamplingEventResponse(
        id=event.id,
        session_id=event.session_id,
        requester=event.requester,
        host_client_id=event.host_client_id,
        model=event.model,
        prompt_template_version=event.prompt_template_version,
        source_facts_ref=event.source_facts_ref,
        validation_result=event.validation_result,
        fallback_path=event.fallback_path.value,
        event_hash=event.event_hash,
        created_at=event.created_at,
    )


@router.get("/{session_id}/sampling-events", response_model=list[CompanionSamplingEventResponse])
def list_sampling_events(
    session_id: str,
    current_user: CurrentUser,
    settings_repo: RecallSettingsRepo,
    session_repo: CompanionSessionRepo,
    event_repo: CompanionSamplingEventRepo,
):
    _enabled(settings_repo, current_user.id)
    _owned(session_repo, current_user.id, session_id)
    return [
        CompanionSamplingEventResponse(
            id=event.id,
            session_id=event.session_id,
            requester=event.requester,
            host_client_id=event.host_client_id,
            model=event.model,
            prompt_template_version=event.prompt_template_version,
            source_facts_ref=event.source_facts_ref,
            validation_result=event.validation_result,
            fallback_path=event.fallback_path.value,
            event_hash=event.event_hash,
            created_at=event.created_at,
        )
        for event in event_repo.list_for_session(current_user.id, session_id)
    ]


# --- Local-AI/deterministic companion reply fallback (#195 TODO 0) ---------


@router.post("/{session_id}/reply", response_model=CompanionReplyResponse)
async def generate_reply(
    session_id: str,
    payload: CompanionReplyRequest,
    current_user: CurrentUser,
    settings_repo: RecallSettingsRepo,
    session_repo: CompanionSessionRepo,
    provider: OptionalAIProvider,
):
    """The fallback path when MCP client sampling is unavailable or its
    result fails validation: a configured local AI provider, else
    deterministic content (#187's `companion_coach` discipline). This
    never becomes Diagnosis/ReviewState/InterventionOutcome truth — only
    editable, evidence-cited display content, exactly like #187's own
    boundary. Read-only, so it needs no confirmation gate (#195 TODO 3).
    """
    _enabled(settings_repo, current_user.id)
    _owned(session_repo, current_user.id, session_id)
    try:
        request = CoachRequest(
            task=payload.task,
            target_language=payload.target_language,
            intervention_type=payload.intervention_type,
            evidence=tuple(CoachEvidence(item.evidence_id, item.fact, item.source) for item in payload.evidence),
            allowed_claims=tuple(payload.allowed_claims),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    content = None
    if provider is not None:
        try:
            prompt = build_coach_prompt(request)
            text = await provider.generate_field(
                "companion_reply", request.task, None, request.target_language, prompt
            )
            content = validate_generated_content(
                # generate_field returns bare prose, not the sampling
                # contract's {text, evidence_ids} shape, so every supplied
                # evidence id is cited rather than trusting the model to
                # pick a subset — the same "caller cleans" split
                # AIProvider's other methods already use.
                {"text": text, "evidence_ids": [item.evidence_id for item in request.evidence]},
                request,
                content_type=payload.intervention_type,
                provider="local_ai",
                model=getattr(provider, "model_name", None),
            )
        except CoachContentRejected:
            content = None
        except Exception:  # noqa: BLE001 - any provider failure falls back safely
            content = None
    if content is None:
        content = deterministic_fallback(request, content_type=payload.intervention_type)
    return CompanionReplyResponse(
        text=content.text,
        evidence_ids=list(content.evidence_ids),
        content_type=content.content_type,
        provider=content.provider,
        model=content.model,
        editable=content.editable,
    )
