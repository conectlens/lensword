"""Intervention plan endpoints (issue #185 TODO 4, issue #192 `/me/interventions`).

Two audiences share this file. `router` is per-word: the plans still
awaiting a learner decision, and acting on one — reject, postpone, or choose
an alternative strategy. Generating a plan itself has no endpoint: it only
ever happens as a side effect of `RunDiagnosisForWordUseCase` (review answer
submission), the same "no separate write path" pattern diagnoses and
knowledge edges already follow.

`me_router` is account-wide: issue #192's `/me/interventions` companion
resource, which has no single word to scope to — the same reasoning
`weaknesses.py` and `observations.py` apply to their own `/me` endpoints,
and previously had no real endpoint to call at all (a permanent
`{"items": [], "available": False}` MCP-side stub).
"""
from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import CurrentUser, InterventionRepo, WordRepo
from app.api.schemas.interventions import (
    ChooseAlternativeRequest,
    InterventionPlanListResponse,
    InterventionPlanResponse,
)
from app.application.use_cases.intervention import (
    ChooseAlternativeInterventionUseCase,
    ListActiveInterventionPlansUseCase,
    PostponeInterventionPlanUseCase,
    RejectInterventionPlanUseCase,
)
from app.domain.exceptions import EntityNotFoundError, ValidationError
from app.domain.services.diagnosis_contracts import InterventionPlan

router = APIRouter(prefix="/api/v1/words/{word_id}/interventions", tags=["diagnosis"])
me_router = APIRouter(prefix="/api/v1/me", tags=["interventions"])

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200


def _response(p: InterventionPlan) -> InterventionPlanResponse:
    return InterventionPlanResponse(
        id=p.id,
        word_id=p.word_id,
        diagnosis_outcome=p.diagnosis_outcome,
        strategy=p.strategy,
        policy_version=p.policy_version,
        eligible=p.eligible,
        rationale=p.rationale,
        planned_at=p.planned_at,
        second_word_id=p.second_word_id,
        prerequisite_ids=list(p.prerequisite_ids),
    )


def _require_owned_word(word_repo: WordRepo, user_id: int, word_id: int):
    words = word_repo.list_all_for_user(user_id)
    if next((w for w in words if w.id == word_id), None) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Word not found")


@router.get("", response_model=list[InterventionPlanResponse])
def list_active_interventions(
    word_id: int, current_user: CurrentUser, word_repo: WordRepo, intervention_repo: InterventionRepo
):
    """Plans not yet resolved/abandoned/rejected — what the review UI has
    to show the learner a decision on (TODO 4)."""
    _require_owned_word(word_repo, current_user.id, word_id)
    plans = ListActiveInterventionPlansUseCase(intervention_repo).execute(current_user.id, word_id)
    return [_response(p) for p in plans]


@router.post("/{plan_id}/reject", response_model=InterventionPlanResponse)
def reject_intervention(
    word_id: int, plan_id: int, current_user: CurrentUser, word_repo: WordRepo, intervention_repo: InterventionRepo
):
    _require_owned_word(word_repo, current_user.id, word_id)
    try:
        plan = _get_plan_or_404(intervention_repo, current_user.id, word_id, plan_id)
        RejectInterventionPlanUseCase(intervention_repo).execute(current_user.id, plan_id)
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _response(plan)


@router.post("/{plan_id}/postpone", response_model=InterventionPlanResponse)
def postpone_intervention(
    word_id: int, plan_id: int, current_user: CurrentUser, word_repo: WordRepo, intervention_repo: InterventionRepo
):
    _require_owned_word(word_repo, current_user.id, word_id)
    try:
        plan = _get_plan_or_404(intervention_repo, current_user.id, word_id, plan_id)
        PostponeInterventionPlanUseCase(intervention_repo).execute(current_user.id, plan_id)
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _response(plan)


@router.post("/{plan_id}/alternative", response_model=InterventionPlanResponse)
def choose_alternative_intervention(
    word_id: int,
    plan_id: int,
    payload: ChooseAlternativeRequest,
    current_user: CurrentUser,
    word_repo: WordRepo,
    intervention_repo: InterventionRepo,
):
    _require_owned_word(word_repo, current_user.id, word_id)
    try:
        _get_plan_or_404(intervention_repo, current_user.id, word_id, plan_id)
        new_plan = ChooseAlternativeInterventionUseCase(intervention_repo).execute(
            current_user.id, plan_id, payload.strategy
        )
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _response(new_plan)


def _get_plan_or_404(intervention_repo: InterventionRepo, user_id: int, word_id: int, plan_id: int) -> InterventionPlan:
    plan = intervention_repo.get_plan(user_id, plan_id)
    # 404 rather than a bare "not found" whether the plan is missing,
    # belongs to another word, or belongs to another account — the same
    # tenant-isolation-by-404 pattern diagnosis.py already uses.
    if plan is None or plan.word_id != word_id:
        raise EntityNotFoundError("InterventionPlan", plan_id)
    return plan


def _decode_offset_cursor(cursor: str | None) -> int:
    if not cursor:
        return 0
    try:
        value = int(cursor)
    except ValueError:
        return 0
    return value if value >= 0 else 0


@me_router.get("/interventions", response_model=InterventionPlanListResponse)
def list_my_interventions(
    current_user: CurrentUser,
    intervention_repo: InterventionRepo,
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    cursor: str | None = None,
) -> InterventionPlanListResponse:
    """Every planned intervention across this account's whole vocabulary,
    newest first — not just the ones still awaiting a decision (`router`'s
    `list_active_interventions` above, scoped to one word). Backs issue
    #192's `lensword://me/interventions` companion resource.
    """
    offset = _decode_offset_cursor(cursor)
    rows = intervention_repo.list_all_for_user(current_user.id, limit=limit + 1, offset=offset)
    has_more = len(rows) > limit
    rows = rows[:limit]
    return InterventionPlanListResponse(
        items=[_response(plan) for plan in rows],
        next_cursor=str(offset + limit) if has_more else None,
    )
