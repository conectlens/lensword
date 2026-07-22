from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUser, ReviewSessionRepo, UserRepo, WordRepo
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
    StartReviewSessionUseCase,
    SubmitAnswerUseCase,
)
from app.domain.exceptions import EntityNotFoundError, NoWordsDueError, PermissionDeniedError
from app.domain.services.spaced_repetition import SpacedRepetitionScheduler

router = APIRouter(prefix="/api/v1/review", tags=["review"])

_scheduler = SpacedRepetitionScheduler()


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
    payload: StartReviewSessionRequest, current_user: CurrentUser, session_repo: ReviewSessionRepo, word_repo: WordRepo
) -> StartReviewSessionResponse:
    try:
        session, words = StartReviewSessionUseCase(session_repo, word_repo).execute(
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
) -> SubmitAnswerResponse:
    try:
        result = SubmitAnswerUseCase(session_repo, word_repo, _scheduler).execute(
            current_user.id, session_id, payload.word_id, payload.outcome, payload.response_time_ms
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
