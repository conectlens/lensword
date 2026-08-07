"""Versioned, policy-gated MCP invocation boundary."""
from hashlib import sha256
from json import dumps
from pathlib import PurePath
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from app.application.mcp.contracts import CONTRACT_VERSION, capabilities, validate_payload
from app.application.mcp.dispatcher import MCPDispatcher, UnboundMCPToolError, UnknownMCPToolError
from app.application.mcp.idempotency import IdempotencyStore
from app.application.mcp.bindings import (
    add_word_handler, check_known_term_handler, create_study_session_handler, due_reviews_handler,
    explain_for_user_handler, extract_vocabulary_handler, finish_companion_session_handler,
    generate_exercises_handler, get_companion_session_handler, language_profile_handler,
    learning_progress_handler, pause_companion_session_handler, record_answer_handler,
    record_context_occurrence_handler, resume_companion_session_handler, search_words_handler,
    start_companion_session_handler, suggest_stretch_vocabulary_handler,
)
from app.api.deps import (
    CompanionSessionRepo, CurrentUser, DbSession, DiagnosisRepo, GroupRepo, LearningObservationRepo,
    OptionalAIProvider, PracticeExerciseRepo, RecallSettingsRepo, ReviewSessionRepo, WordRepo,
)
from app.domain.services.mcp_policy import AccessClass, GrantMode, MCPGrant, MCPPolicyGate, redact_and_chain
from app.domain.services.spaced_repetition import SpacedRepetitionScheduler
from app.domain.value_objects import utcnow
from app.infrastructure.models import MCPAuditEventModel, MCPGrantModel

router = APIRouter(prefix="/api/v1/mcp", tags=["mcp"])
_request_calls: dict = {}

class InvokeRequest(BaseModel):
    tool: str = Field(min_length=1, max_length=255)
    requester: str = Field(min_length=1, max_length=255)
    workspace: str = Field(min_length=1, max_length=1024)
    payload: dict = Field(default_factory=dict)

@router.get("/capabilities")
def get_capabilities(version: str | None = None) -> dict:
    if version is not None and version.split(".", 1)[0] != CONTRACT_VERSION.split(".", 1)[0]:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Unsupported MCP major version")
    return capabilities()


def _valid_workspace(workspace: str) -> bool:
    return PurePath(workspace).is_absolute() and ".." not in PurePath(workspace).parts


def _audit(db, request: InvokeRequest, decision: str, *, payload_bytes: int) -> None:
    previous = db.query(MCPAuditEventModel).order_by(MCPAuditEventModel.id.desc()).first()
    event, event_hash = redact_and_chain(
        previous.event_hash if previous else "0" * 64,
        {
            "server": "lensword", "workspace": request.workspace, "payload_bytes": payload_bytes,
            # The audit trail never stores untrusted prompts/tool arguments.
            "payload_sha256": sha256(dumps(request.payload, sort_keys=True, default=str).encode()).hexdigest(),
        },
    )
    db.add(MCPAuditEventModel(requester=request.requester, tool=request.tool, decision=decision, event=event, previous_hash=previous.event_hash if previous else "0" * 64, event_hash=event_hash, created_at=utcnow()))
    db.flush()

@router.post("/invoke")
async def invoke(
    request: InvokeRequest, current_user: CurrentUser, db: DbSession, groups: GroupRepo, words: WordRepo,
    sessions: ReviewSessionRepo, exercises: PracticeExerciseRepo, provider: OptionalAIProvider,
    companion_sessions: CompanionSessionRepo, recall_settings: RecallSettingsRepo,
    diagnoses: DiagnosisRepo, observations: LearningObservationRepo,
) -> dict:
    payload_bytes = len(dumps(request.payload, sort_keys=True, default=str).encode())
    if not _valid_workspace(request.workspace):
        _audit(db, request, "invalid_workspace", payload_bytes=payload_bytes)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="invalid_workspace")
    grants = [MCPGrant(item.requester, item.server, item.tool, AccessClass(item.access), item.workspace, GrantMode(item.mode), item.expires_at, item.revoked_at, item.consumed_at) for item in db.query(MCPGrantModel)]
    handlers = {
        "lensword.add_word": add_word_handler(words, groups), "lensword.search_words": search_words_handler(words, groups),
        "lensword.get_due_reviews": due_reviews_handler(words), "lensword.create_study_session": create_study_session_handler(sessions, words),
        "lensword.generate_exercises": generate_exercises_handler(exercises, words, groups), "lensword.get_learning_progress": learning_progress_handler(sessions),
        "lensword.record_answer": record_answer_handler(sessions, words, SpacedRepetitionScheduler()), "lensword.extract_vocabulary": extract_vocabulary_handler(groups, provider),
        "lensword.start_companion_session": start_companion_session_handler(companion_sessions, recall_settings),
        "lensword.get_companion_session": get_companion_session_handler(companion_sessions, recall_settings),
        "lensword.resume_companion_session": resume_companion_session_handler(companion_sessions, recall_settings),
        "lensword.pause_companion_session": pause_companion_session_handler(companion_sessions, recall_settings),
        "lensword.finish_companion_session": finish_companion_session_handler(companion_sessions, recall_settings, provider),
        "lensword.get_language_profile": language_profile_handler(groups, words), "lensword.check_known_term": check_known_term_handler(words, groups),
        "lensword.explain_for_user": explain_for_user_handler(words, groups, diagnoses),
        "lensword.suggest_stretch_vocabulary": suggest_stretch_vocabulary_handler(words, groups),
        "lensword.record_context_occurrence": record_context_occurrence_handler(words, groups, observations),
    }
    dispatcher = MCPDispatcher(handlers)
    try: contract = dispatcher.contract_for(request.tool)
    except UnknownMCPToolError as exc:
        _audit(db, request, "unknown_tool", payload_bytes=payload_bytes)
        raise HTTPException(status_code=404, detail="Unknown MCP tool") from exc
    validation_error = validate_payload(contract, request.payload)
    if validation_error:
        _audit(db, request, "validation_error", payload_bytes=payload_bytes)
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=validation_error)
    decision = MCPPolicyGate(grants, calls=_request_calls).authorize(request.requester, "lensword", request.tool, contract.access, request.workspace, payload_bytes, utcnow())
    _audit(db, request, decision.reason, payload_bytes=payload_bytes)
    if not decision.allowed: raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=decision.reason)
    matching_grant = next((item for item in db.query(MCPGrantModel) if (item.requester, item.server, item.tool, item.access, item.workspace) == (request.requester, "lensword", request.tool, contract.access.value, request.workspace)), None)
    if matching_grant is not None and matching_grant.mode == GrantMode.ONCE.value:
        matching_grant.consumed_at = utcnow(); db.flush()
    request_id = request.payload.get("request_id")
    store = IdempotencyStore(db)
    if contract.access != AccessClass.READ and isinstance(request_id, str):
        try: replay = store.replay(request.requester, request_id, request.tool)
        except ValueError as exc:
            _audit(db, request, "idempotency_conflict", payload_bytes=payload_bytes)
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        if replay is not None: return replay
    try: result = await dispatcher.dispatch_async(current_user.id or 0, request.tool, request.payload)
    except UnboundMCPToolError as exc: raise HTTPException(status_code=501, detail="MCP tool is not bound") from exc
    if contract.access != AccessClass.READ and isinstance(request_id, str): result = store.record(request.requester, request_id, request.tool, result, utcnow())
    return result
