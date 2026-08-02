"""Role-play scenarios (issue #136).

An attempt wraps a conversation from #135 rather than replacing it, so the
transport, corrections and bounded history are reused. Messages go through the
existing `/conversations/{id}/message` route — there is deliberately no second
message endpoint, because two ways to send a turn would eventually disagree
about corrections.
"""
import logging

from fastapi import APIRouter, HTTPException, status

from app.api.deps import (
    ConversationRepo,
    CurrentUser,
    OptionalAIProvider,
    ScenarioAttemptRepo,
)
from app.api.schemas.scenarios import (
    ScenarioAttemptResponse,
    ScenarioResponse,
    StartAttemptRequest,
)
from app.domain.exceptions import AIProviderUnavailableError
from app.domain.services.conversation import Speaker, Turn
from app.domain.services.scenarios import (
    CATALOG,
    MIN_LEARNER_TURNS_TO_SCORE,
    can_score,
    get_scenario,
    unscored,
    validate_evaluation,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/scenarios", tags=["scenario role-play"])


@router.get("", response_model=list[ScenarioResponse])
def list_scenarios() -> list[ScenarioResponse]:
    """The catalog.

    Unauthenticated: it is a fixed product list with nothing about any learner
    in it, and requiring a token to see what practice exists would be
    ceremony.
    """
    return [
        ScenarioResponse(
            key=scenario.key,
            title=scenario.title,
            briefing=scenario.briefing,
            goals=list(scenario.goals),
            suggested_topics=list(scenario.suggested_topics),
        )
        for scenario in CATALOG
    ]


@router.post("/attempts", response_model=ScenarioAttemptResponse, status_code=status.HTTP_201_CREATED)
def start_attempt(
    payload: StartAttemptRequest,
    current_user: CurrentUser,
    conversations: ConversationRepo,
    attempts: ScenarioAttemptRepo,
) -> ScenarioAttemptResponse:
    scenario = get_scenario(payload.scenario_key)
    if scenario is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scenario not found")

    session = conversations.start(
        user_id=current_user.id,
        target_language=payload.target_language,
        difficulty=payload.difficulty.value,
        # The tutor's role, not the learner's briefing. The learner is never
        # shown the instruction the model is given.
        scenario=scenario.tutor_role,
    )
    attempt = attempts.add(current_user.id, session.id, scenario.key)
    return _to_response(attempt, scenario)


@router.get("/attempts", response_model=list[ScenarioAttemptResponse])
def list_attempts(
    current_user: CurrentUser, attempts: ScenarioAttemptRepo
) -> list[ScenarioAttemptResponse]:
    out = []
    for attempt in attempts.list_for_user(current_user.id):
        scenario = get_scenario(attempt.scenario_key)
        if scenario is None:
            # A retired scenario leaves its attempts readable rather than
            # breaking the history page.
            continue
        out.append(_to_response(attempt, scenario))
    return out


@router.get("/attempts/{attempt_id}", response_model=ScenarioAttemptResponse)
def get_attempt(
    attempt_id: int, current_user: CurrentUser, attempts: ScenarioAttemptRepo
) -> ScenarioAttemptResponse:
    attempt = _owned(attempts, attempt_id, current_user.id)
    scenario = get_scenario(attempt.scenario_key)
    if scenario is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scenario not found")
    return _to_response(attempt, scenario)


@router.post("/attempts/{attempt_id}/finish", response_model=ScenarioAttemptResponse)
async def finish_attempt(
    attempt_id: int,
    current_user: CurrentUser,
    attempts: ScenarioAttemptRepo,
    conversations: ConversationRepo,
    provider: OptionalAIProvider,
) -> ScenarioAttemptResponse:
    attempt = _owned(attempts, attempt_id, current_user.id)
    scenario = get_scenario(attempt.scenario_key)
    if scenario is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scenario not found")

    session = conversations.get(attempt.session_id)
    transcript = [
        Turn(speaker=Speaker(m.speaker), text=m.text) for m in (session.messages if session else [])
    ]
    learner_turns = sum(1 for turn in transcript if turn.speaker is Speaker.LEARNER)

    # Refused before the model is asked. Scoring three messages produces a
    # confident number the learner will believe because it looks precise.
    if not can_score(learner_turns):
        evaluation = unscored(
            f"Not enough to judge yet — say at least {MIN_LEARNER_TURNS_TO_SCORE} things "
            "and finish again."
        )
    elif provider is None:
        evaluation = unscored("AI is not configured for this deployment, so this cannot be scored.")
    else:
        try:
            raw = await provider.evaluate_scenario(scenario, transcript)
            evaluation = validate_evaluation(raw, scenario)
        except (AIProviderUnavailableError, ValueError) as exc:
            logger.info("Scenario evaluation failed: %s", exc)
            evaluation = unscored(str(exc) or "The attempt could not be scored just now.")

    conversations.end(attempt.session_id)
    stored = attempts.finish(attempt_id, _evaluation_json(evaluation))
    return _to_response(stored, scenario)


def _owned(attempts, attempt_id: int, user_id: int):
    """404 rather than 403 for someone else's attempt — a distinguishable 403
    would confirm it exists to anyone enumerating ids."""
    attempt = attempts.get(attempt_id)
    if attempt is None or attempt.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attempt not found")
    return attempt


def _evaluation_json(evaluation) -> dict:
    return {
        "scored": evaluation.scored,
        "scores": [
            {"dimension": s.dimension.value, "score": s.score, "comment": s.comment}
            for s in evaluation.scores
        ],
        "summary": evaluation.summary,
        "goals_met": evaluation.goals_met,
        "detail": evaluation.detail,
        "overall": evaluation.overall,
    }


def _to_response(attempt, scenario) -> ScenarioAttemptResponse:
    return ScenarioAttemptResponse(
        id=attempt.id,
        session_id=attempt.session_id,
        scenario=ScenarioResponse(
            key=scenario.key,
            title=scenario.title,
            briefing=scenario.briefing,
            goals=list(scenario.goals),
            suggested_topics=list(scenario.suggested_topics),
        ),
        started_at=attempt.started_at,
        finished_at=attempt.finished_at,
        evaluation=attempt.evaluation,
    )
