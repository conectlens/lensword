from fastapi import APIRouter, HTTPException, status

from app.api.deps import (
    AcquisitionStateRepo,
    CurrentUser,
    DiagnosisRepo,
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
    SessionSummaryResponse,
    StartReviewSessionRequest,
    StartReviewSessionResponse,
    SubmitAnswerRequest,
    SubmitAnswerResponse,
    WeeklyProgressResponse,
)
from app.application.use_cases.review import (
    CompleteReviewSessionUseCase,
    GetWeeklyProgressUseCase,
    ObservationInput,
    StartReviewSessionUseCase,
    SubmitAnswerUseCase,
)
from app.domain.exceptions import EntityNotFoundError, NoWordsDueError, PermissionDeniedError
from app.domain.services.spaced_repetition import FSRSScheduler, SpacedRepetitionScheduler

router = APIRouter(prefix="/api/v1/review", tags=["review"])

_scheduler = SpacedRepetitionScheduler()
_fsrs_scheduler = FSRSScheduler()


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
) -> StartReviewSessionResponse:
    try:
        session, words = StartReviewSessionUseCase(session_repo, word_repo, mistake_repo).execute(
            current_user.id, payload.mode, payload.group_id, payload.limit
        )
    except NoWordsDueError as exc:
        _raise_for(exc)
    return StartReviewSessionResponse(session_id=session.id, mode=session.mode, words=[word_to_response(w) for w in words])


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
