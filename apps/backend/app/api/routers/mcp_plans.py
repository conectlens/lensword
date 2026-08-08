"""Authenticated preview-and-confirm execution for bounded MCP plans."""
from __future__ import annotations

from dataclasses import dataclass
from time import monotonic

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.api.deps import (
    CompanionActivityRepo, CompanionSessionRepo, CompanionTaskRepo, CurrentUser, DbSession, DiagnosisRepo, GroupRepo,
    KnowledgeEdgeRepo, LearningObservationRepo, MnemonicRepo, PerUserAIProvider, PracticeExerciseRepo,
    RecallSettingsRepo, ReviewSessionRepo, RoomRepo, WordRepo, WordRevisionRepo,
)
from app.api.mcp_auth import MCPActor
from app.api.routers.mcp import InvokeRequest, invoke
from app.application.mcp.planner import CommandPlanner, LearningPlan

router = APIRouter(prefix="/api/v1/mcp/plans", tags=["mcp"])
PLAN_TTL_SECONDS = 600


class PlanPreviewRequest(BaseModel):
    command: str = Field(min_length=1, max_length=1_000)
    workspace: str = Field(min_length=1, max_length=1_024)
    source_text: str | None = Field(default=None, max_length=20_000)


class PlanExecuteRequest(BaseModel):
    confirmed: bool = False
    cancelled: bool = False


@dataclass(slots=True)
class StoredPlan:
    owner_id: int
    request: PlanPreviewRequest
    plan: LearningPlan
    expires_at: float


_plans: dict[str, StoredPlan] = {}


def _get_plan(plan_id: str, owner_id: int) -> StoredPlan:
    stored = _plans.get(plan_id)
    if stored is None or stored.expires_at < monotonic():
        _plans.pop(plan_id, None)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plan was not found or expired")
    if stored.owner_id != owner_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plan was not found")
    return stored


@router.post("/preview")
def preview(payload: PlanPreviewRequest, current_user: CurrentUser, groups: GroupRepo) -> dict:
    plan = CommandPlanner().plan(payload.command, groups.list_by_owner(current_user.id or 0), source_text=payload.source_text)
    _plans[plan.id] = StoredPlan(current_user.id or 0, payload, plan, monotonic() + PLAN_TTL_SECONDS)
    return plan.preview()


@router.post("/{plan_id}/execute")
async def execute(
    plan_id: str, payload: PlanExecuteRequest, current_user: CurrentUser, db: DbSession, groups: GroupRepo,
    words: WordRepo, sessions: ReviewSessionRepo, exercises: PracticeExerciseRepo, provider: PerUserAIProvider,
    companion_sessions: CompanionSessionRepo, companion_tasks: CompanionTaskRepo, recall_settings: RecallSettingsRepo,
    diagnoses: DiagnosisRepo, observations: LearningObservationRepo, companion_activities: CompanionActivityRepo,
    rooms: RoomRepo, mnemonics: MnemonicRepo, edges: KnowledgeEdgeRepo, revisions: WordRevisionRepo,
) -> dict:
    stored = _get_plan(plan_id, current_user.id or 0)
    if payload.cancelled:
        _plans.pop(plan_id, None)
        return {"status": "cancelled", "steps": []}
    if not stored.plan.executable:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=stored.plan.reason)
    if stored.plan.requires_confirmation and not payload.confirmed:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Plan confirmation is required", headers={"X-LensWord-Plan": plan_id})
    # Identity for the underlying /invoke call is the already-authenticated
    # `current_user` (issue #196 TODO 2), never a caller-supplied string —
    # `PlanPreviewRequest` used to carry its own `requester` field here,
    # which was the same trust-the-request-body gap `mcp.py`'s `InvokeRequest`
    # had, just one hop removed. See app/api/mcp_auth.py's module docstring.
    actor = MCPActor.for_login(current_user)
    results = []
    for step in stored.plan.steps:
        try:
            result = await invoke(InvokeRequest(tool=step.tool, workspace=stored.request.workspace, payload=step.payload), actor, db, groups, words, sessions, exercises, provider, companion_sessions, companion_tasks, recall_settings, diagnoses, observations, companion_activities, rooms, mnemonics, edges, revisions)
            results.append({"id": step.id, "tool": step.tool, "status": "completed", "result": result})
        except HTTPException as exc:
            results.append({"id": step.id, "tool": step.tool, "status": "failed", "detail": exc.detail})
            _plans.pop(plan_id, None)
            return {"status": "partial_failure", "steps": results}
    _plans.pop(plan_id, None)
    return {"status": "completed", "steps": results}
