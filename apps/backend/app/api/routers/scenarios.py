"""Role-play scenarios (issue #136).

An attempt wraps a conversation from #135 rather than replacing it, so the
transport, corrections and bounded history are reused. Messages go through the
existing `/conversations/{id}/message` route — there is deliberately no second
message endpoint, because two ways to send a turn would eventually disagree
about corrections.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import (
    ConversationRepo,
    CurrentUser,
    KnowledgeEdgeRepo,
    OptionalAIProvider,
    ScenarioAttemptRepo,
    WordRepo,
    rate_limit_ai,
)
from app.api.schemas.scenarios import (
    ScenarioAttemptResponse,
    ScenarioResponse,
    ScenarioVocabularyResponse,
    StartAttemptRequest,
)
from app.application.use_cases.knowledge_graph import graph_for_user
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


# Below this, a learner is not prepared enough for the suggestion list to be
# worth showing as a list — it is worth saying so instead.
SPARSE_BELOW = 5


@router.get("/{scenario_key}/vocabulary", response_model=ScenarioVocabularyResponse)
def scenario_vocabulary(
    scenario_key: str,
    current_user: CurrentUser,
    word_repo: WordRepo,
    edge_repo: KnowledgeEdgeRepo,
) -> ScenarioVocabularyResponse:
    """Words worth revising before a scenario (issue #144).

    Only words the learner already holds. Suggesting vocabulary they do not
    have would be a shopping list dressed as preparation.

    On-topic words come from their own topic tags; related ones come through
    the knowledge graph (#138), so a word filed under a different topic but
    *confused with* an on-topic one still surfaces — that confusion is exactly
    what will trip them up mid-conversation.
    """
    scenario = get_scenario(scenario_key)
    if scenario is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scenario not found")

    words = word_repo.list_all_for_user(current_user.id)
    wanted = {topic.strip().casefold() for topic in scenario.suggested_topics}

    on_topic = [
        word
        for word in words
        if any((topic or "").strip().casefold() in wanted for topic in word.topics)
    ]
    on_topic_ids = {word.id for word in on_topic}

    graph = graph_for_user(words, edge_repo, current_user.id)
    related_ids: dict[int, float] = {}
    for word in on_topic:
        for edge in graph.related(word.id, limit=10):
            other = edge.target_id if edge.source_id == word.id else edge.source_id
            if other in on_topic_ids:
                continue
            related_ids[other] = max(related_ids.get(other, 0.0), edge.strength)

    by_id = {word.id: word for word in words}
    related = [
        by_id[word_id]
        for word_id, _ in sorted(related_ids.items(), key=lambda item: (-item[1], item[0]))
        if word_id in by_id
    ][:15]

    total = len(on_topic) + len(related)
    sparse = total < SPARSE_BELOW
    detail = (
        f"You have {total} word(s) for this situation. Add a few before "
        "practising, or go ahead and see what you are missing."
        if sparse
        else f"{total} word(s) you already know for this situation."
    )

    return ScenarioVocabularyResponse(
        scenario_key=scenario.key,
        on_topic=[_word_brief(word) for word in on_topic[:25]],
        related=[_word_brief(word) for word in related],
        sparse=sparse,
        detail=detail,
    )


def _word_brief(word) -> dict:
    return {
        "id": word.id,
        "term": word.term,
        "translations": list(word.translations)[:3],
        "cefr_level": word.cefr_level,
    }


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


@router.post("/attempts/{attempt_id}/finish", response_model=ScenarioAttemptResponse, dependencies=[Depends(rate_limit_ai)])
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
