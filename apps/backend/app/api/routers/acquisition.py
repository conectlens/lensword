"""Graduated acquisition ladder endpoints (#180, issue #184 TODO 3).

Backend surface only: current state, the due list a "stabilize this word"
session would render, explicit entry, and submitting one rung's outcome.
The actual review-experience UI (a short session view, accessibility and
keyboard-only flows) is out of this PR's scope — see the tracking issue
this PR's description links for that and for TODO 5's live retention/
workload cohort evaluation, neither of which a backend change alone can
deliver.
"""
from fastapi import APIRouter, HTTPException, status

from app.api.deps import AcquisitionStateRepo, CurrentUser, RecallSettingsRepo, WordRepo
from app.api.schemas.acquisition import AcquisitionAnswerRequest, AcquisitionStateResponse
from app.application.use_cases.acquisition import EnterAcquisitionUseCase, SubmitAcquisitionAnswerUseCase
from app.domain.services.acquisition import AcquisitionScheduler
from app.domain.services.diagnosis_contracts import AcquisitionState
from app.domain.services.spaced_repetition import FSRSScheduler, SpacedRepetitionScheduler
from app.domain.value_objects import utcnow

router = APIRouter(tags=["acquisition"])

_scheduler = SpacedRepetitionScheduler()
_fsrs_scheduler = FSRSScheduler()


def _response(state: AcquisitionState) -> AcquisitionStateResponse:
    return AcquisitionStateResponse(
        word_id=state.word_id,
        rung=state.rung,
        ladder_version=state.ladder_version,
        started_at=state.started_at,
        updated_at=state.updated_at,
        due_at=AcquisitionScheduler().due_at(state),
        graduated=state.graduated,
        entry_reason=state.entry_reason,
    )


def _require_owned_word(word_repo: WordRepo, user_id: int, word_id: int):
    words = word_repo.list_all_for_user(user_id)
    word = next((w for w in words if w.id == word_id), None)
    if word is None:
        # Same tenant-isolation reasoning as diagnosis.py and graph.py: a
        # distinguishable 403 would confirm the id exists to an account
        # that does not own it.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Word not found")
    return word


def _require_enabled(settings_repo: RecallSettingsRepo, user_id: int) -> None:
    settings = settings_repo.get_by_user(user_id)
    if not (settings and settings.acquisition_loop_enabled):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The acquisition loop is not enabled for this account",
        )


@router.get("/api/v1/words/{word_id}/acquisition", response_model=AcquisitionStateResponse | None)
def current_state(
    word_id: int, current_user: CurrentUser, word_repo: WordRepo, acquisition_repo: AcquisitionStateRepo
):
    """The word's current ladder position, or null if it has never
    entered the loop — a word with no ladder and an account with the
    feature off both look like this rather than an error."""
    _require_owned_word(word_repo, current_user.id, word_id)
    state = acquisition_repo.get_for_word(current_user.id, word_id)
    return _response(state) if state is not None else None


@router.post(
    "/api/v1/words/{word_id}/acquisition/start",
    response_model=AcquisitionStateResponse,
    status_code=status.HTTP_201_CREATED,
)
def start(
    word_id: int,
    current_user: CurrentUser,
    word_repo: WordRepo,
    acquisition_repo: AcquisitionStateRepo,
    settings_repo: RecallSettingsRepo,
):
    """TODO 4's explicit-user-choice entry — always allowed to start a
    ladder (an already-active one is returned unchanged, not restarted),
    unlike diagnosis-driven entry which only fires from a review answer."""
    _require_owned_word(word_repo, current_user.id, word_id)
    _require_enabled(settings_repo, current_user.id)
    state = EnterAcquisitionUseCase(acquisition_repo).execute(
        current_user.id, word_id, explicit_choice=True, now=utcnow()
    )
    return _response(state)


@router.post("/api/v1/words/{word_id}/acquisition/answer", response_model=AcquisitionStateResponse | None)
def answer(
    word_id: int,
    payload: AcquisitionAnswerRequest,
    current_user: CurrentUser,
    word_repo: WordRepo,
    acquisition_repo: AcquisitionStateRepo,
    settings_repo: RecallSettingsRepo,
):
    """One micro-recall. Null when there is no active ladder for this word
    — the client raced graduation or the loop was never started, neither
    of which is an error worth surfacing as one."""
    _require_owned_word(word_repo, current_user.id, word_id)
    settings = settings_repo.get_by_user(current_user.id)
    selected_scheduler = _fsrs_scheduler if settings and settings.scheduler == "fsrs" else _scheduler
    state = SubmitAcquisitionAnswerUseCase(acquisition_repo, word_repo, selected_scheduler).execute(
        current_user.id, word_id, payload.outcome, payload.operation_id, now=utcnow()
    )
    return _response(state) if state is not None else None


@router.get("/api/v1/acquisition/due", response_model=list[AcquisitionStateResponse])
def due(current_user: CurrentUser, acquisition_repo: AcquisitionStateRepo, limit: int = 50):
    """Every word of this account's whose ladder is due right now — the
    content a "stabilize this word" session (TODO 3) would render, scoped
    to the caller's own account only."""
    states = acquisition_repo.list_due(utcnow(), user_id=current_user.id, limit=limit)
    return [_response(s) for s in states]
