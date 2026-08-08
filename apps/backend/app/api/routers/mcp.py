"""Versioned, policy-gated MCP invocation boundary.

Caller identity (`requester`) is resolved from an authenticated token by
`app.api.mcp_auth.get_mcp_actor` — never accepted as a request-body field.
See mcp_auth.py's module docstring for the vulnerability this closes
(issue #196 TODO 2): a caller-supplied `requester` string used to be trusted
directly for grant lookups, rate limiting and the audit trail.
"""
from hashlib import sha256
from json import dumps
from pathlib import PurePosixPath
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from app.application.mcp.contracts import CONTRACT_VERSION, capabilities, validate_payload
from app.application.mcp.dispatcher import MCPDispatcher, UnboundMCPToolError, UnknownMCPToolError
from app.application.mcp.idempotency import IdempotencyStore
from app.application.mcp.bindings import (
    add_word_handler, begin_learning_activity_handler, cancel_companion_task_handler, check_known_term_handler,
    create_group_handler, create_room_handler, create_study_session_handler, delete_word_handler,
    due_reviews_handler, explain_evidence_handler, explain_for_user_handler,
    extract_vocabulary_handler, finish_companion_session_handler, finish_learning_activity_handler,
    generate_exercises_handler, generate_mnemonic_handler, get_activity_result_handler,
    get_companion_session_handler, get_mnemonics_handler, get_word_map_handler,
    get_companion_task_handler, language_profile_handler, learning_progress_handler,
    list_group_words_handler, list_groups_handler, list_rooms_handler,
    pause_companion_session_handler, place_word_in_room_handler, record_answer_handler,
    record_context_occurrence_handler,
    request_hint_handler, resume_companion_session_handler, search_words_handler,
    start_companion_session_handler, start_extraction_task_handler,
    submit_activity_response_handler, suggest_stretch_vocabulary_handler, update_word_handler,
)
from app.api.deps import (
    CompanionActivityRepo, CompanionSessionRepo, CompanionTaskRepo, DbSession, DiagnosisRepo, GroupRepo,
    KnowledgeEdgeRepo, LearningObservationRepo, MnemonicRepo, PracticeExerciseRepo,
    RecallSettingsRepo, ReviewSessionRepo, RoomRepo, WordRepo, WordRevisionRepo,
)
from app.api.mcp_auth import CurrentMCPActor, MCPActor, PerActorAIProvider
from app.config import get_settings
from app.domain.services.mcp_policy import AccessClass, GrantMode, MCPGrant, MCPPolicyGate, redact_and_chain
from app.domain.services.mcp_scopes import SCOPE_RESOURCES
from app.domain.services.spaced_repetition import SpacedRepetitionScheduler
from app.domain.value_objects import utcnow
from app.infrastructure.models import MCPAuditEventModel, MCPGrantModel

router = APIRouter(prefix="/api/v1/mcp", tags=["mcp"])
_request_calls: dict = {}

class InvokeRequest(BaseModel):
    tool: str = Field(min_length=1, max_length=255)
    workspace: str = Field(min_length=1, max_length=1024)
    payload: dict = Field(default_factory=dict)

@router.get("/capabilities")
def get_capabilities(version: str | None = None) -> dict:
    if version is not None and version.split(".", 1)[0] != CONTRACT_VERSION.split(".", 1)[0]:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Unsupported MCP major version")
    return capabilities()


def is_valid_workspace(workspace: str) -> bool:
    # PurePosixPath, deliberately not the platform-dependent `pathlib.PurePath`
    # (which resolves to PureWindowsPath on a Windows host, where
    # "/approved" is NOT absolute without a drive letter — a real,
    # platform-dependent correctness bug in what is supposed to be a
    # security boundary check, since every workspace string in this
    # codebase is written POSIX-style ("/approved", never "C:\approved").
    # This must decide identically on every host the backend runs on.
    #
    # The one exception: settings.mcp_remote_workspace, the sentinel a
    # remote OAuth grant (Claude.ai, no local filesystem) is recorded under
    # instead of a real path — see that setting's docstring for why a path
    # doesn't apply there at all.
    if workspace == get_settings().mcp_remote_workspace:
        return True
    return PurePosixPath(workspace).is_absolute() and ".." not in PurePosixPath(workspace).parts


def _audit(db, requester: str, request: InvokeRequest, decision: str, *, payload_bytes: int) -> None:
    previous = db.query(MCPAuditEventModel).order_by(MCPAuditEventModel.id.desc()).first()
    event, event_hash = redact_and_chain(
        previous.event_hash if previous else "0" * 64,
        {
            "server": "lensword", "workspace": request.workspace, "payload_bytes": payload_bytes,
            # The audit trail never stores untrusted prompts/tool arguments.
            "payload_sha256": sha256(dumps(request.payload, sort_keys=True, default=str).encode()).hexdigest(),
        },
    )
    db.add(MCPAuditEventModel(requester=requester, tool=request.tool, decision=decision, event=event, previous_hash=previous.event_hash if previous else "0" * 64, event_hash=event_hash, created_at=utcnow()))
    db.flush()

def _handlers(groups, words, sessions, exercises, provider, companion_sessions, companion_tasks, recall_settings, diagnoses, observations, companion_activities, rooms, mnemonics, edges, revisions) -> dict:
    return {
        # Group management, word lifecycle, memory palace, MnemoLab and the
        # knowledge graph. Every one of these delegates to a use case that
        # already backs the equivalent REST route, so the MCP surface and the
        # web app enforce ownership through the same code path rather than
        # two parallel authorization checks that could drift.
        "lensword_create_group": create_group_handler(groups),
        "lensword_list_groups": list_groups_handler(groups, words),
        "lensword_list_group_words": list_group_words_handler(groups, words),
        "lensword_update_word": update_word_handler(words, groups, revisions),
        "lensword_delete_word": delete_word_handler(words, groups),
        "lensword_list_rooms": list_rooms_handler(rooms, words),
        "lensword_create_room": create_room_handler(rooms, groups),
        "lensword_place_word_in_room": place_word_in_room_handler(rooms, words),
        "lensword_get_mnemonics": get_mnemonics_handler(mnemonics, words, groups),
        "lensword_generate_mnemonic": generate_mnemonic_handler(mnemonics, words, groups, provider),
        "lensword_get_word_map": get_word_map_handler(words, groups, edges),
        "lensword_add_word": add_word_handler(words, groups), "lensword_search_words": search_words_handler(words, groups),
        "lensword_get_due_reviews": due_reviews_handler(words), "lensword_create_study_session": create_study_session_handler(sessions, words),
        "lensword_generate_exercises": generate_exercises_handler(exercises, words, groups), "lensword_get_learning_progress": learning_progress_handler(sessions),
        "lensword_record_answer": record_answer_handler(sessions, words, SpacedRepetitionScheduler()), "lensword_extract_vocabulary": extract_vocabulary_handler(groups, provider),
        "lensword_start_extraction_task": start_extraction_task_handler(companion_tasks, companion_sessions, recall_settings),
        "lensword_get_companion_task": get_companion_task_handler(companion_tasks, companion_sessions, recall_settings),
        "lensword_cancel_companion_task": cancel_companion_task_handler(companion_tasks, companion_sessions, recall_settings),
        "lensword_start_companion_session": start_companion_session_handler(companion_sessions, recall_settings),
        "lensword_get_companion_session": get_companion_session_handler(companion_sessions, recall_settings),
        "lensword_resume_companion_session": resume_companion_session_handler(companion_sessions, recall_settings),
        "lensword_pause_companion_session": pause_companion_session_handler(companion_sessions, recall_settings),
        "lensword_finish_companion_session": finish_companion_session_handler(companion_sessions, recall_settings, provider),
        "lensword_get_language_profile": language_profile_handler(groups, words), "lensword_check_known_term": check_known_term_handler(words, groups),
        "lensword_explain_for_user": explain_for_user_handler(words, groups, diagnoses),
        "lensword_suggest_stretch_vocabulary": suggest_stretch_vocabulary_handler(words, groups),
        "lensword_record_context_occurrence": record_context_occurrence_handler(words, groups, observations),
        "lensword_begin_learning_activity": begin_learning_activity_handler(
            companion_activities, companion_sessions, recall_settings, words, groups
        ),
        "lensword_submit_activity_response": submit_activity_response_handler(
            companion_activities, companion_sessions, recall_settings, observations
        ),
        "lensword_get_activity_result": get_activity_result_handler(
            companion_activities, companion_sessions, recall_settings
        ),
        "lensword_finish_learning_activity": finish_learning_activity_handler(
            companion_activities, companion_sessions, recall_settings
        ),
        "lensword_request_hint": request_hint_handler(
            companion_activities, companion_sessions, recall_settings, words, groups
        ),
        "lensword_explain_evidence": explain_evidence_handler(
            companion_activities, companion_sessions, recall_settings, words, groups, diagnoses
        ),
    }

@router.post("/invoke")
async def invoke(
    request: InvokeRequest, actor: CurrentMCPActor, db: DbSession, groups: GroupRepo, words: WordRepo,
    sessions: ReviewSessionRepo, exercises: PracticeExerciseRepo, provider: PerActorAIProvider,
    companion_sessions: CompanionSessionRepo, companion_tasks: CompanionTaskRepo, recall_settings: RecallSettingsRepo,
    diagnoses: DiagnosisRepo, observations: LearningObservationRepo, companion_activities: CompanionActivityRepo,
    rooms: RoomRepo, mnemonics: MnemonicRepo, edges: KnowledgeEdgeRepo, revisions: WordRevisionRepo,
) -> dict:
    requester = actor.requester
    payload_bytes = len(dumps(request.payload, sort_keys=True, default=str).encode())
    if not is_valid_workspace(request.workspace):
        _audit(db, requester, request, "invalid_workspace", payload_bytes=payload_bytes)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="invalid_workspace")
    grants = [MCPGrant(item.requester, item.server, item.tool, AccessClass(item.access), item.workspace, GrantMode(item.mode), item.expires_at, item.revoked_at, item.consumed_at) for item in db.query(MCPGrantModel)]
    dispatcher = MCPDispatcher(_handlers(groups, words, sessions, exercises, provider, companion_sessions, companion_tasks, recall_settings, diagnoses, observations, companion_activities, rooms, mnemonics, edges, revisions))
    try: contract = dispatcher.contract_for(request.tool)
    except UnknownMCPToolError as exc:
        _audit(db, requester, request, "unknown_tool", payload_bytes=payload_bytes)
        raise HTTPException(status_code=404, detail="Unknown MCP tool") from exc
    validation_error = validate_payload(contract, request.payload)
    if validation_error:
        _audit(db, requester, request, "validation_error", payload_bytes=payload_bytes)
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=validation_error)
    request_id = request.payload.get("request_id")
    # Mandatory idempotency for writes (issue #196 TODO 4): the contract
    # schema already requires `request_id` for every write tool
    # (contracts.py's `_schema(..., write=True)`), so a write payload missing
    # it already fails `validate_payload` above with "missing required
    # payload field: request_id" before this point is ever reached. This is
    # just the belt-and-suspenders form of that same rule, kept here so the
    # invariant is enforced even if a future contract forgets `write=True`.
    if contract.access != AccessClass.READ and not isinstance(request_id, str):
        _audit(db, requester, request, "idempotency_key_required", payload_bytes=payload_bytes)
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="request_id is required for write tools")
    decision = MCPPolicyGate(grants, calls=_request_calls).authorize(requester, "lensword", request.tool, contract.access, request.workspace, payload_bytes, utcnow())
    _audit(db, requester, request, decision.reason, payload_bytes=payload_bytes)
    if not decision.allowed: raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=decision.reason)
    matching_grant = next((item for item in db.query(MCPGrantModel) if (item.requester, item.server, item.tool, item.access, item.workspace) == (requester, "lensword", request.tool, contract.access.value, request.workspace)), None)
    if matching_grant is not None and matching_grant.mode == GrantMode.ONCE.value:
        matching_grant.consumed_at = utcnow(); db.flush()
    store = IdempotencyStore(db)
    if contract.access != AccessClass.READ and isinstance(request_id, str):
        try: replay = store.replay(requester, request_id, request.tool)
        except ValueError as exc:
            _audit(db, requester, request, "idempotency_conflict", payload_bytes=payload_bytes)
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        if replay is not None: return replay
    try: result = await dispatcher.dispatch_async(actor.user.id or 0, request.tool, request.payload)
    except UnboundMCPToolError as exc: raise HTTPException(status_code=501, detail="MCP tool is not bound") from exc
    if contract.access != AccessClass.READ and isinstance(request_id, str): result = store.record(requester, request_id, request.tool, result, utcnow())
    return result


@router.get("/resource")
async def read_resource(
    uri: str, workspace: str, actor: CurrentMCPActor, db: DbSession, groups: GroupRepo, words: WordRepo,
    sessions: ReviewSessionRepo, exercises: PracticeExerciseRepo, provider: PerActorAIProvider,
    companion_sessions: CompanionSessionRepo, companion_tasks: CompanionTaskRepo, recall_settings: RecallSettingsRepo,
    diagnoses: DiagnosisRepo, observations: LearningObservationRepo, companion_activities: CompanionActivityRepo,
    rooms: RoomRepo, mnemonics: MnemonicRepo, edges: KnowledgeEdgeRepo, revisions: WordRevisionRepo,
) -> dict:
    """Scoped resource read for both local and remote MCP callers.

    Deliberately narrower than the stdio transport's `BackendClient.resource`
    (apps/mcp/lensword_mcp/server.py), which reads arbitrary `lensword://`
    URIs via direct REST passthrough authenticated only by "is this a valid
    bearer token for some user" — appropriate for a local companion holding
    the same trust level as the browser, but not for a remote OAuth token
    scoped to a specific narrow grant. Wiring that passthrough to an
    OAuth-scoped token would silently widen a narrow grant (e.g.
    `session-read`) into unrestricted REST access, defeating the scope
    model this issue asks for. This endpoint instead only serves the
    resources listed in `mcp_scopes.SCOPE_RESOURCES`, and only after the
    same `MCPPolicyGate` grant check `/invoke` uses for the tool that backs
    each resource — see that dict for exactly which URIs are covered today
    (a deliberately small starting set; the PR description documents the
    rest as a known gap for remote callers).
    """
    requester = actor.requester
    resource_to_tool = {
        "lensword://me/due": "lensword_get_due_reviews",
        "lensword://me/active-words": "lensword_search_words",
        "lensword://me/progress": "lensword_get_learning_progress",
    }
    known_resources = {r for tools in SCOPE_RESOURCES.values() for r in tools}
    if uri not in resource_to_tool or uri not in known_resources:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown or unsupported MCP resource")
    if not is_valid_workspace(workspace):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="invalid_workspace")
    tool = resource_to_tool[uri]
    dispatcher = MCPDispatcher(_handlers(groups, words, sessions, exercises, provider, companion_sessions, companion_tasks, recall_settings, diagnoses, observations, companion_activities, rooms, mnemonics, edges, revisions))
    contract = dispatcher.contract_for(tool)
    grants = [MCPGrant(item.requester, item.server, item.tool, AccessClass(item.access), item.workspace, GrantMode(item.mode), item.expires_at, item.revoked_at, item.consumed_at) for item in db.query(MCPGrantModel)]
    decision = MCPPolicyGate(grants, calls=_request_calls).authorize(requester, "lensword", tool, contract.access, workspace, 0, utcnow())
    if not decision.allowed:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=decision.reason)
    payload = {"limit": 100} if tool in ("lensword_get_due_reviews", "lensword_search_words") else {}
    if tool == "lensword_search_words":
        payload["query"] = ""
    try:
        return await dispatcher.dispatch_async(actor.user.id or 0, tool, payload)
    except UnboundMCPToolError as exc:
        raise HTTPException(status_code=501, detail="MCP tool is not bound") from exc
