"""Provider-neutral companion session API contracts (#193)."""
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.domain.services.companion_sessions import CompanionSessionStatus, CompanionTurnRole


class CompanionSessionCreateRequest(BaseModel):
    connection_id: str = Field(min_length=1, max_length=128)
    client_id: str = Field(min_length=1, max_length=128)
    goal: str | None = Field(default=None, max_length=500)
    language: str | None = Field(default=None, max_length=64)
    group_id: int | None = Field(default=None, ge=1)
    difficulty: str | None = Field(default=None, max_length=32)
    active_activity: str | None = Field(default=None, max_length=128)
    consent_snapshot: dict[str, Any] = Field(default_factory=dict)


class CompanionTurnRequest(BaseModel):
    role: CompanionTurnRole
    content: str = Field(min_length=1, max_length=10000)
    activity_id: str | None = Field(default=None, max_length=128)
    operation_id: str | None = Field(default=None, max_length=128)


class CompanionTurnResponse(BaseModel):
    id: int
    session_id: str
    role: CompanionTurnRole
    content: str
    activity_id: str | None
    operation_id: str | None
    created_at: datetime


class CompanionSessionResponse(BaseModel):
    id: str
    connection_id: str
    client_id: str
    goal: str | None
    language: str | None
    group_id: int | None
    difficulty: str | None
    active_activity: str | None
    consent_snapshot: dict[str, Any]
    summary: str | None
    status: CompanionSessionStatus
    revision: int
    created_at: datetime
    updated_at: datetime
    turns: list[CompanionTurnResponse] = []


class CompanionExportResponse(BaseModel):
    session: CompanionSessionResponse
    format: str = "lensword.companion-session.v1"


class CompanionActionResponse(BaseModel):
    session: CompanionSessionResponse


class CompanionChatRequest(BaseModel):
    content: str = Field(min_length=1, max_length=10000)
    operation_id: str | None = Field(default=None, max_length=128)


class CompanionChatResponse(BaseModel):
    """One in-app chat exchange.

    `POST /turns` records a turn that some external companion already
    produced; this records the user's turn *and* asks the configured
    provider for the answer, which is what an in-app chat surface needs.

    Always HTTP 200 with a `status`, matching the conversation tutor: a
    provider that is switched off or briefly down is a normal state of a
    healthy install, not a client error. `user_turn` is present for every
    status, so a failed reply still leaves what the user typed on screen.
    """

    status: str  # ok | disabled | unavailable
    user_turn: CompanionTurnResponse
    assistant_turn: CompanionTurnResponse | None = None
    detail: str | None = None


class CompanionSessionTransferRequest(BaseModel):
    """Reassigns which companion connection currently controls a session
    (#193 TODO 3), e.g. handing an in-progress session from a desktop client
    to a mobile one without losing turns or restarting."""

    connection_id: str = Field(min_length=1, max_length=128)
    client_id: str = Field(min_length=1, max_length=128)


class CompanionActivityCreateRequest(BaseModel):
    activity_type: str = Field(min_length=1, max_length=32)
    prompt: str = Field(min_length=1, max_length=4000)
    expected_evaluation: dict[str, Any] = Field(default_factory=dict)
    operation_id: str | None = Field(default=None, max_length=128)


class CompanionActivityResponse(BaseModel):
    id: str
    session_id: str
    activity_type: str
    prompt: str
    expected_evaluation: dict[str, Any]
    status: str
    response: str | None
    result: dict[str, Any] | None
    operation_id: str | None
    started_at: datetime
    updated_at: datetime
    revision: int
    hints_used: int = 0


class CompanionActivityAnswerRequest(BaseModel):
    response: str = Field(min_length=1, max_length=10000)


class CompanionActivityHintResponse(BaseModel):
    """#194 TODO 1's `request_hint`."""

    activity: CompanionActivityResponse
    hint: str
    hints_used: int
    hints_remaining: int


class CompanionActivityEvidenceResponse(BaseModel):
    """#194 TODO 1's `explain_evidence`."""

    activity_id: str
    activity_type: str
    prompt: str
    status: str
    result: dict[str, Any] | None
    hints_used: int
    word_explanation: dict[str, Any] | None = None


class CompanionActivityPlanRequest(BaseModel):
    max_activities: int = Field(default=5, ge=1, le=8)


class CompanionActivityPlanConfirmRequest(BaseModel):
    confirmed: bool = False


class CompanionTaskCreateRequest(BaseModel):
    task_type: str = Field(min_length=1, max_length=32)
    total_units: int = Field(ge=1, le=10000)
    expires_in_seconds: int = Field(default=300, ge=1, le=86400)
    operation_id: str | None = Field(default=None, max_length=128)
    # Bounded execution parameters for the background executor (#197 TODO 3),
    # e.g. precomputed extraction candidates. Only meaningful for task types
    # the executor actually runs; anything else is simply never read.
    input: dict[str, Any] | None = Field(default=None)


class CompanionTaskProgressRequest(BaseModel):
    completed_units: int = Field(ge=0, le=10000)


class CompanionTaskCompleteRequest(BaseModel):
    result: dict[str, Any] = Field(default_factory=dict)


class CompanionTaskResponse(BaseModel):
    id: str
    session_id: str
    task_type: str
    status: str
    total_units: int
    completed_units: int
    progress: float
    result: dict[str, Any] | None
    error: str | None
    operation_id: str | None
    expires_at: datetime
    created_at: datetime
    updated_at: datetime
    revision: int
    input: dict[str, Any] | None = None


# --- Bounded companion loop budgets (#195 TODO 2) --------------------------


class CompanionLoopStartRequest(BaseModel):
    tool_calls: int = Field(default=8, ge=0, le=1000)
    samples: int = Field(default=3, ge=0, le=1000)
    elapsed_seconds: float = Field(default=300.0, ge=0, le=86400)
    generated_tokens: int = Field(default=2_000, ge=0, le=1_000_000)
    activities: int = Field(default=10, ge=0, le=1000)
    writes: int = Field(default=10, ge=0, le=1000)


class CompanionLoopReserveRequest(BaseModel):
    kind: str = Field(min_length=1, max_length=16)
    amount: int = Field(default=1, ge=1, le=1_000_000)


class CompanionLoopStopRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=32)


class CompanionLoopStateResponse(BaseModel):
    session_id: str
    tool_calls: int
    samples: int
    generated_tokens: int
    activities: int
    writes: int
    consecutive_failures: int
    stopped_reason: str | None
    started_at: datetime
    updated_at: datetime
    revision: int


# --- Sampling provenance/audit (#195 TODO 4) --------------------------------


class CompanionSamplingEventCreateRequest(BaseModel):
    requester: str = Field(min_length=1, max_length=255)
    host_client_id: str | None = Field(default=None, max_length=128)
    model: str | None = Field(default=None, max_length=128)
    prompt_template_version: str = Field(min_length=1, max_length=32)
    source_facts_ref: str = Field(min_length=1, max_length=128)
    validation_result: str = Field(min_length=1, max_length=255)
    fallback_path: str = Field(min_length=1, max_length=64)


class CompanionSamplingEventResponse(BaseModel):
    id: int
    session_id: str
    requester: str
    host_client_id: str | None
    model: str | None
    prompt_template_version: str
    source_facts_ref: str
    validation_result: str
    fallback_path: str
    event_hash: str
    created_at: datetime


# --- Local-AI/deterministic companion reply fallback (#195 TODO 0) ---------
# The client-sampling path itself lives in apps/mcp (only the MCP process
# talks to the host); this endpoint is only the fallback #187's coach
# discipline already defines: a local AI provider if one is configured,
# otherwise deterministic content. Never diagnosis/mastery/retention truth.


class CompanionReplyEvidenceRequest(BaseModel):
    evidence_id: str = Field(min_length=1, max_length=64)
    fact: str = Field(min_length=1, max_length=1_000)
    source: str = Field(min_length=1, max_length=128)


class CompanionReplyRequest(BaseModel):
    task: str = Field(min_length=1, max_length=500)
    target_language: str = Field(min_length=1, max_length=64)
    intervention_type: str = Field(min_length=1, max_length=32)
    evidence: list[CompanionReplyEvidenceRequest] = Field(min_length=1, max_length=20)
    allowed_claims: list[str] = Field(default_factory=list, max_length=20)


class CompanionReplyResponse(BaseModel):
    text: str
    evidence_ids: list[str]
    content_type: str
    provider: str
    model: str | None
    editable: bool
