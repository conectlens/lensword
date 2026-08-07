from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import (
    AcquisitionStateRepo,
    CurrentUser,
    DiagnosisRepo,
    InterventionRepo,
    KnowledgeEdgeRepo,
    LearningObservationRepo,
    MistakeEventRepo,
    RecallSettingsRepo,
    ReviewSessionRepo,
    UserRepo,
    WordRepo,
)
from app.api.mappers import word_to_response
from app.api.schemas.review import (
    CompleteSessionRequest,
    ContrastAnswerRequest,
    ContrastAnswerResponse,
    ContrastCardResponse,
    SessionSummaryResponse,
    StartReviewSessionRequest,
    StartReviewSessionResponse,
    SubmitAnswerRequest,
    SubmitAnswerResponse,
    WeeklyProgressResponse,
)
from app.application.use_cases.intervention import active_plans
from app.application.use_cases.knowledge_graph import graph_for_user
from app.domain.services.contrast_cards import (
    ContrastCard,
    answer_contrast_card,
    build_contrast_cards,
    pair_decisions_from_plans,
)
from app.domain.services.knowledge_graph import Relation
from app.domain.value_objects import utcnow
from app.application.use_cases.review import (
    MULTIPLE_CHOICE_MODES,
    CompleteReviewSessionUseCase,
    GetWeeklyProgressUseCase,
    ObservationInput,
    StartReviewSessionUseCase,
    SubmitAnswerUseCase,
    build_mcq_options_for_words,
)
from app.domain.exceptions import EntityNotFoundError, NoWordsDueError, PermissionDeniedError
from app.domain.services.spaced_repetition import FSRSScheduler, SpacedRepetitionScheduler

router = APIRouter(prefix="/api/v1/review", tags=["review"])

_scheduler = SpacedRepetitionScheduler()
_fsrs_scheduler = FSRSScheduler()


@router.get("/contrast-cards", response_model=list[ContrastCardResponse])
def contrast_cards(
    current_user: CurrentUser,
    word_repo: WordRepo,
    settings_repo: RecallSettingsRepo,
    edge_repo: KnowledgeEdgeRepo,
    intervention_repo: InterventionRepo,
    limit: int = Query(default=20, ge=1, le=20),
) -> list[ContrastCardResponse]:
    settings = settings_repo.get_by_user(current_user.id)
    # Both switches are required: semantic relatedness is the Phase 0
    # umbrella flag, while this feature has its own conservative sub-setting.
    if not settings or not (settings.semantic_relatedness_enabled and settings.contrast_cards_enabled):
        return []
    words = word_repo.list_all_for_user(current_user.id)
    # #206 TODO 5: source pairs from #185's real diagnosis-driven plans when
    # one exists for a pair; the graph fallback inside build_contrast_cards
    # only fills in pairs no plan has an opinion on. `active_plans` also
    # carries any `isolate` decision, which always wins over the fallback.
    decisions = pair_decisions_from_plans(
        tuple(active_plans(
            intervention_repo.list_all_for_user(current_user.id),
            intervention_repo.list_all_outcomes_for_user(current_user.id),
        ))
    )
    cards = build_contrast_cards(
        words,
        graph_for_user(words, edge_repo, current_user.id),
        enabled=True,
        minimum_stability=settings.contrast_min_stability,
        intervention_decisions=decisions,
        limit=limit,
    )
    return [
        ContrastCardResponse(
            word_ids=card.word_ids,
            terms=card.terms,
            relation=card.relation.value,
            prompt=card.prompt,
        )
        for card in cards
    ]


@router.post("/contrast-cards/answer", response_model=ContrastAnswerResponse)
def answer_contrast(
    payload: ContrastAnswerRequest,
    current_user: CurrentUser,
    settings_repo: RecallSettingsRepo,
) -> ContrastAnswerResponse:
    settings = settings_repo.get_by_user(current_user.id)
    if not settings or not (settings.semantic_relatedness_enabled and settings.contrast_cards_enabled):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contrast cards are disabled")
    try:
        card = ContrastCard(
            word_ids=payload.word_ids,
            terms=payload.terms,
            relation=Relation(payload.relation),
            prompt=payload.prompt,
        )
        answer_contrast_card(
            card,
            first_word_note=payload.first_word_note,
            second_word_note=payload.second_word_note,
            distinction=payload.distinction,
            answered_at=utcnow(),
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    # Deliberately no SubmitAnswerUseCase call: a contrast response is not an
    # FSRS review and therefore cannot mutate either word's due_at.
    return ContrastAnswerResponse()


def _raise_for(exc: Exception):
    if isinstance(exc, EntityNotFoundError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    if isinstance(exc, PermissionDeniedError):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    if isinstance(exc, NoWordsDueError):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    raise exc


@router.post("/sessions", response_model=StartReviewSessionResponse, status_code=status.HTTP_201_CREATED)
def start_session(
    payload: StartReviewSessionRequest,
    current_user: CurrentUser,
    session_repo: ReviewSessionRepo,
    word_repo: WordRepo,
    mistake_repo: MistakeEventRepo,
    settings_repo: RecallSettingsRepo,
    edge_repo: KnowledgeEdgeRepo,
) -> StartReviewSessionResponse:
    try:
        session, words = StartReviewSessionUseCase(session_repo, word_repo, mistake_repo).execute(
            current_user.id, payload.mode, payload.group_id, payload.limit
        )
    except NoWordsDueError as exc:
        _raise_for(exc)

    # #205: only a multiple-choice mode needs options at all, and only with
    # the relatedness flag on — everything else stays byte-identical to
    # before this field existed, matching ADR 0007's "no flag, no branch"
    # discipline for every other opt-in surface in this router.
    settings = settings_repo.get_by_user(current_user.id)
    mcq_selections = {}
    if payload.mode in MULTIPLE_CHOICE_MODES and bool(settings and settings.semantic_relatedness_enabled):
        all_words = word_repo.list_all_for_user(current_user.id)
        graph = graph_for_user(all_words, edge_repo, current_user.id)
        mcq_selections = build_mcq_options_for_words(words, all_words, graph)

    responses = []
    for word in words:
        response = word_to_response(word)
        selection = mcq_selections.get(word.id)
        if selection is not None:
            response.mcq_options = selection.options
        responses.append(response)

    return StartReviewSessionResponse(session_id=session.id, mode=session.mode, words=responses)


@router.post("/sessions/{session_id}/answers", response_model=SubmitAnswerResponse)
def submit_answer(
    session_id: int,
    payload: SubmitAnswerRequest,
    current_user: CurrentUser,
    session_repo: ReviewSessionRepo,
    word_repo: WordRepo,
    settings_repo: RecallSettingsRepo,
    mistake_repo: MistakeEventRepo,
    observation_repo: LearningObservationRepo,
    edge_repo: KnowledgeEdgeRepo,
    diagnosis_repo: DiagnosisRepo,
    acquisition_repo: AcquisitionStateRepo,
    intervention_repo: InterventionRepo,
) -> SubmitAnswerResponse:
    try:
        settings = settings_repo.get_by_user(current_user.id)
        selected_scheduler = _fsrs_scheduler if settings and settings.scheduler == "fsrs" else _scheduler
        # ADR 0007: with the flag off, this path never reaches
        # learning_observations at all — not just "records nothing", the
        # repository itself is never wired into the use case.
        diagnosis_enabled = bool(settings and settings.learning_diagnosis_enabled)
        # #184: a diagnosis-driven ladder entry only matters if a diagnosis
        # is even being produced this request — gated on both flags, not
        # just its own, so acquisition_loop_enabled alone (diagnosis off)
        # cannot trigger entry from a diagnosis that was never computed.
        acquisition_enabled = diagnosis_enabled and bool(settings and settings.acquisition_loop_enabled)
        result = SubmitAnswerUseCase(
            session_repo,
            word_repo,
            selected_scheduler,
            mistake_repo,
            observation_repo if diagnosis_enabled else None,
            edge_repo,
            diagnosis_repo if diagnosis_enabled else None,
            acquisition_repo if acquisition_enabled else None,
            intervention_repo if diagnosis_enabled else None,
        ).execute(
            current_user.id,
            session_id,
            payload.word_id,
            payload.outcome,
            payload.response_time_ms,
            payload.attempted_answer,
            ObservationInput(
                operation_id=payload.operation_id,
                prompt_direction=payload.prompt_direction,
                hint_used=payload.hint_used,
                answer_format=payload.answer_format,
                modality=payload.modality,
                intervention_plan_ref=payload.intervention_plan_ref,
                self_reported_confidence=payload.self_reported_confidence,
            ) if diagnosis_enabled else None,
        )
    except (EntityNotFoundError, PermissionDeniedError) as exc:
        _raise_for(exc)
    return SubmitAnswerResponse(word=word_to_response(result.word), was_new_word_learned=result.was_new_word)


@router.post("/sessions/{session_id}/complete", response_model=SessionSummaryResponse)
def complete_session(
    session_id: int,
    payload: CompleteSessionRequest,
    current_user: CurrentUser,
    session_repo: ReviewSessionRepo,
    user_repo: UserRepo,
    word_repo: WordRepo,
) -> SessionSummaryResponse:
    try:
        session = CompleteReviewSessionUseCase(session_repo, user_repo, word_repo).execute(
            current_user.id, session_id, payload.new_words_learned_count
        )
    except (EntityNotFoundError, PermissionDeniedError) as exc:
        _raise_for(exc)
    return SessionSummaryResponse(
        id=session.id,
        mode=session.mode,
        started_at=session.started_at,
        ended_at=session.ended_at,
        duration_seconds=session.duration_seconds,
        words_reviewed=session.words_reviewed_count,
        correct_count=session.correct_count,
        incorrect_count=session.incorrect_count,
        new_words_learned=session.new_words_learned_count,
        accuracy_percent=session.accuracy_percent,
    )


@router.get("/weekly-progress", response_model=WeeklyProgressResponse)
def weekly_progress(current_user: CurrentUser, session_repo: ReviewSessionRepo) -> WeeklyProgressResponse:
    counts = GetWeeklyProgressUseCase(session_repo).execute(current_user.id)
    return WeeklyProgressResponse(counts_by_day=counts)
