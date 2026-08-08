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
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import (
    CurrentUser,
    DbSession,
    DiagnosisRepo,
    InterventionRepo,
    PerUserAIProvider,
    WordRepo,
    rate_limit_ai,
)
from app.api.schemas.interventions import (
    ChooseAlternativeRequest,
    InterventionExplanationDisabled,
    InterventionExplanationOk,
    InterventionExplanationRejected,
    InterventionExplanationResponse,
    InterventionExplanationUnavailable,
    InterventionPlanListResponse,
    InterventionPlanResponse,
)
from app.application.use_cases.intervention import (
    ChooseAlternativeInterventionUseCase,
    ExplainInterventionUseCase,
    ListActiveInterventionPlansUseCase,
    PostponeInterventionPlanUseCase,
    RejectInterventionPlanUseCase,
)
from app.config import get_effective_ai_settings
from app.domain.exceptions import EntityNotFoundError, ValidationError
from app.domain.services.ai_cache import AIResponseCache, CacheKey
from app.domain.services.companion_coach import CoachContent, CoachRequest
from app.domain.services.diagnosis_contracts import InterventionPlan
from app.domain.value_objects import utcnow

router = APIRouter(prefix="/api/v1/words/{word_id}/interventions", tags=["diagnosis"])
me_router = APIRouter(prefix="/api/v1/me", tags=["interventions"])

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200

# One cache per process, shared across requests but never across users — the
# same #139 reasoning app/api/routers/ai.py's own `_cache` uses. A plan's
# generated content is worth reusing within a sitting; it is not worth
# reusing across a model or policy change, which is why both are part of
# the key (#187 TODO 5).
_coach_cache = AIResponseCache()


def _coach_cache_key(user_id: int, plan: InterventionPlan, request: CoachRequest) -> CacheKey:
    settings = get_effective_ai_settings()
    return CacheKey.build(
        user_id=user_id,
        provider=settings.ai_provider or "none",
        model=settings.ollama_model or "none",
        operation="coach_explain",
        payload={
            "plan_id": plan.id,
            "policy_version": plan.policy_version,
            "content_type": request.intervention_type,
            # The evidence itself, not just its count — a plan whose
            # underlying evidence changed (e.g. a later diagnosis re-ran)
            # must not serve a stale answer just because the plan id
            # matched.
            "evidence": [(item.evidence_id, item.fact) for item in request.evidence],
        },
    )


def _explanation_response(
    outcome: str, content: CoachContent, detail: str | None
) -> InterventionExplanationResponse:
    fields = {
        "text": content.text,
        "evidence_ids": list(content.evidence_ids),
        "content_type": content.content_type,
        "editable": content.editable,
    }
    if outcome == "disabled":
        return InterventionExplanationDisabled(**fields)
    if outcome == "unavailable":
        return InterventionExplanationUnavailable(detail=detail or "", **fields)
    if outcome == "rejected":
        return InterventionExplanationRejected(detail=detail or "", **fields)
    return InterventionExplanationOk(provider=content.provider, model=content.model, **fields)


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


@router.post(
    "/{plan_id}/explain",
    response_model=InterventionExplanationResponse,
    dependencies=[Depends(rate_limit_ai)],
)
async def explain_intervention(
    word_id: int,
    plan_id: int,
    current_user: CurrentUser,
    word_repo: WordRepo,
    intervention_repo: InterventionRepo,
    diagnosis_repo: DiagnosisRepo,
    ai_provider: PerUserAIProvider,
    db: DbSession,
) -> InterventionExplanationResponse:
    """Issue #187 TODO 2: evidence-grounded, AI-generated content for an
    existing plan — contrast exercise / prerequisite lesson / mnemonic
    alternatives / plain explanation, chosen by the plan's own `strategy`,
    never by the caller. Nothing here is written back to the plan (see
    `InterventionPlan`'s docstring: this epic's facts are append-only) — the
    response is what the learner edits or rejects client-side.

    `async def` so a slow generation waits on the event loop, and the
    pooled DB connection is released with `db.close()` before that await —
    the same reason and the same pattern `mnemonics.py`'s `suggest_mnemonic`
    documents (#187 TODO 5): the engine's connection pool is far smaller
    than the number of requests a hung provider can pile up.
    """
    _require_owned_word(word_repo, current_user.id, word_id)
    try:
        plan = _get_plan_or_404(intervention_repo, current_user.id, word_id, plan_id)
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    word = word_repo.get_by_id(word_id)
    target_language = word.target_language.value if word is not None else "unknown"

    use_case = ExplainInterventionUseCase(diagnosis_repo, ai_provider)
    request = use_case.build_request(plan, target_language)

    cache_key = None
    if ai_provider is not None:
        cache_key = _coach_cache_key(current_user.id, plan, request)
        cached = _coach_cache.get(cache_key, utcnow())
        if cached is not None:
            return _explanation_response("ok", cached, None)

    db.close()

    outcome, content, detail = await use_case.generate(request)
    if outcome == "ok" and cache_key is not None:
        # Failures are deliberately never cached (see ai_cache.py's own
        # rule) — a daemon that was unreachable or a generation that was
        # rejected a minute ago may succeed on retry, and caching either
        # would keep serving that non-answer for the whole TTL.
        _coach_cache.put(cache_key, content, utcnow())
    return _explanation_response(outcome, content, detail)


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
