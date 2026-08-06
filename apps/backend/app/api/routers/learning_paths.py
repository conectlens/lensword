"""Learning paths from a stated goal (issue #137).

Generation always answers HTTP 200 with a `status`, the same way mnemonic
suggestions do: a provider switched off or temporarily down is a normal state
of a healthy install, not a server error, and a 500 would tell the learner the
fault was ours.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import CurrentUser, LearningPathRepo, OptionalAIProvider, rate_limit_ai
from app.api.schemas.learning_paths import (
    GeneratePathRequest,
    GeneratePathResponse,
    LearningPathResponse,
    MilestoneResponse,
)
from app.domain.exceptions import AIProviderUnavailableError
from app.domain.services.learning_path import (
    MAX_MILESTONES,
    MIN_MILESTONES,
    InvalidPlanError,
    MilestonePlan,
    clean_goal,
    measure,
    validate_plan,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/learning-paths", tags=["learning paths"])


@router.post("/generate", response_model=GeneratePathResponse, dependencies=[Depends(rate_limit_ai)])
async def generate_path(
    payload: GeneratePathRequest,
    current_user: CurrentUser,
    provider: OptionalAIProvider,
    path_repo: LearningPathRepo,
) -> GeneratePathResponse:
    if provider is None:
        return GeneratePathResponse(
            status="disabled",
            detail="AI is not configured for this deployment, so paths cannot be generated.",
        )

    try:
        goal = clean_goal(payload.goal)
    except InvalidPlanError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc

    try:
        raw = await provider.generate_learning_path(
            goal, payload.target_language, MAX_MILESTONES, MIN_MILESTONES
        )
    except AIProviderUnavailableError as exc:
        return GeneratePathResponse(status="unavailable", detail=str(exc))

    try:
        # Bounded and cleaned before anything is stored. A model asked for a
        # plan will sometimes return thirty steps, or one with an empty title,
        # or a target of five thousand words — none of those are paths.
        plans = validate_plan(raw)
    except InvalidPlanError as exc:
        # Issue #212: this used to be a dead end — the raw payload was
        # never logged anywhere, so a rejected plan was undiagnosable
        # without re-running a whole verification pass. Logged rather than
        # raised further, matching the "always 200" contract this endpoint
        # already states in its own module docstring.
        logger.warning("Learning path plan rejected for goal %r: %s; raw=%r", goal, exc, raw)
        return GeneratePathResponse(status="unavailable", detail=str(exc))

    stored = path_repo.add(
        user_id=current_user.id,
        goal=goal,
        target_language=payload.target_language,
        milestones=plans,
        group_id=payload.group_id,
        ai_provider=getattr(provider, "name", None) or "ollama",
        ai_model=getattr(provider, "model", None),
    )
    return GeneratePathResponse(
        status="ok", path=_to_response(stored, path_repo.words_by_topic(current_user.id))
    )


@router.get("", response_model=list[LearningPathResponse])
def list_paths(current_user: CurrentUser, path_repo: LearningPathRepo) -> list[LearningPathResponse]:
    counts = path_repo.words_by_topic(current_user.id)
    return [_to_response(path, counts) for path in path_repo.list_for_user(current_user.id)]


@router.get("/{path_id}", response_model=LearningPathResponse)
def get_path(path_id: int, current_user: CurrentUser, path_repo: LearningPathRepo) -> LearningPathResponse:
    path = _owned(path_repo, path_id, current_user.id)
    return _to_response(path, path_repo.words_by_topic(current_user.id))


@router.delete("/{path_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_path(path_id: int, current_user: CurrentUser, path_repo: LearningPathRepo) -> None:
    _owned(path_repo, path_id, current_user.id)
    path_repo.delete(path_id)


def _owned(path_repo, path_id: int, user_id: int):
    """Fetch a path, or 404.

    404 rather than 403 for someone else's path: a distinguishable 403 would
    confirm that another account's path exists to anyone enumerating ids, and
    a goal is a personal thing to leak the existence of.
    """
    path = path_repo.get(path_id)
    if path is None or path.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Learning path not found")
    return path


def _to_response(path, words_by_topic: dict) -> LearningPathResponse:
    plans = [
        MilestonePlan(
            title=m.title,
            description=m.description or "",
            topic=m.topic,
            target_word_count=m.target_word_count,
            cefr_level=m.cefr_level,
        )
        for m in sorted(path.milestones, key=lambda m: m.position)
    ]
    progress = measure(path.goal, plans, words_by_topic)

    milestones = [
        MilestoneResponse(
            position=m.position,
            title=m.title,
            description=m.description,
            topic=m.topic,
            target_word_count=m.target_word_count,
            cefr_level=m.cefr_level,
            words_held=m.words_held,
            words_mastered=m.words_mastered,
            complete=m.complete,
            share=m.share,
        )
        for m in progress.milestones
    ]
    next_up = progress.next_milestone

    return LearningPathResponse(
        id=path.id,
        goal=path.goal,
        target_language=path.target_language,
        group_id=path.group_id,
        ai_provider=path.ai_provider,
        ai_model=path.ai_model,
        created_at=path.created_at,
        milestones=milestones,
        completed_count=progress.completed_count,
        share=progress.share,
        next_milestone=next(
            (m for m in milestones if next_up is not None and m.position == next_up.position), None
        ),
    )
