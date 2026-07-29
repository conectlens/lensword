"""Versioned, policy-gated MCP invocation boundary."""
from datetime import datetime
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from app.application.mcp.contracts import capabilities
from app.application.mcp.dispatcher import MCPDispatcher, UnboundMCPToolError, UnknownMCPToolError
from app.application.mcp.idempotency import IdempotencyStore
from app.application.mcp.bindings import add_word_handler, create_study_session_handler, due_reviews_handler, extract_vocabulary_handler, generate_exercises_handler, learning_progress_handler, record_answer_handler, search_words_handler
from app.api.deps import CurrentUser, DbSession, GroupRepo, OptionalAIProvider, PracticeExerciseRepo, ReviewSessionRepo, WordRepo
from app.domain.services.mcp_policy import AccessClass, GrantMode, MCPGrant, MCPPolicyGate
from app.domain.services.spaced_repetition import SpacedRepetitionScheduler
from app.domain.value_objects import utcnow
from app.infrastructure.models import MCPGrantModel

router = APIRouter(prefix="/api/v1/mcp", tags=["mcp"])

class InvokeRequest(BaseModel):
    tool: str = Field(min_length=1, max_length=255)
    requester: str = Field(min_length=1, max_length=255)
    workspace: str = Field(min_length=1, max_length=1024)
    payload: dict = Field(default_factory=dict)

@router.get("/capabilities")
def get_capabilities() -> dict:
    return capabilities()

@router.post("/invoke")
async def invoke(
    request: InvokeRequest, current_user: CurrentUser, db: DbSession, groups: GroupRepo, words: WordRepo,
    sessions: ReviewSessionRepo, exercises: PracticeExerciseRepo, provider: OptionalAIProvider,
) -> dict:
    grants = [MCPGrant(item.requester, item.server, item.tool, AccessClass(item.access), item.workspace, GrantMode(item.mode), item.expires_at, item.revoked_at, item.consumed_at) for item in db.query(MCPGrantModel)]
    handlers = {
        "lensword.add_word": add_word_handler(words, groups), "lensword.search_words": search_words_handler(words, groups),
        "lensword.get_due_reviews": due_reviews_handler(words), "lensword.create_study_session": create_study_session_handler(sessions, words),
        "lensword.generate_exercises": generate_exercises_handler(exercises, words, groups), "lensword.get_learning_progress": learning_progress_handler(sessions),
        "lensword.record_answer": record_answer_handler(sessions, words, SpacedRepetitionScheduler()), "lensword.extract_vocabulary": extract_vocabulary_handler(groups, provider),
    }
    dispatcher = MCPDispatcher(handlers)
    try: contract = dispatcher.contract_for(request.tool)
    except UnknownMCPToolError as exc: raise HTTPException(status_code=404, detail="Unknown MCP tool") from exc
    decision = MCPPolicyGate(grants).authorize(request.requester, "lensword", request.tool, contract.access, request.workspace, len(str(request.payload).encode()), utcnow())
    if not decision.allowed: raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=decision.reason)
    request_id = request.payload.get("request_id")
    store = IdempotencyStore(db)
    if contract.access != AccessClass.READ and isinstance(request_id, str):
        replay = store.replay(request.requester, request_id)
        if replay is not None: return replay
    try: result = await dispatcher.dispatch_async(current_user.id or 0, request.tool, request.payload)
    except UnboundMCPToolError as exc: raise HTTPException(status_code=501, detail="MCP tool is not bound") from exc
    if contract.access != AccessClass.READ and isinstance(request_id, str): result = store.record(request.requester, request_id, request.tool, result, utcnow())
    return result
