"""Learner-facing observation history and correction endpoints (#180, issue #229 TODO 5).

The other half of what #182's evidence model shipped without: a private
view of what LensWord recorded, and a way to say a specific row was wrong
without deleting it. Read-only history and the flag-as-misgraded/
irrelevant action only — evidence-inspection detail beyond what a
diagnosis already cites, and any privacy-policy work around
`context_source` (#229 TODO 3), stay out of this file; see that issue.
"""
import uuid

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import CurrentUser, LearningObservationRepo, WordRepo
from app.api.schemas.observations import (
    CorrectObservationRequest,
    ObservationCorrectionResponse,
    ObservationHistoryItem,
    ObservationHistoryResponse,
)
from app.domain.services.diagnosis_contracts import LearningObservation, ObservationCorrection
from app.domain.value_objects import utcnow

router = APIRouter(prefix="/api/v1/me", tags=["learning observations"])

DEFAULT_HISTORY_LIMIT = 50
MAX_HISTORY_LIMIT = 200


def _correction_response(correction: ObservationCorrection | None) -> ObservationCorrectionResponse | None:
    if correction is None:
        return None
    return ObservationCorrectionResponse(
        correction_id=correction.correction_id,
        reason=correction.reason,
        note=correction.note,
        created_at=correction.created_at,
    )


@router.get("/observations", response_model=ObservationHistoryResponse)
def observation_history(
    current_user: CurrentUser,
    observation_repo: LearningObservationRepo,
    word_repo: WordRepo,
    limit: int = Query(default=DEFAULT_HISTORY_LIMIT, ge=1, le=MAX_HISTORY_LIMIT),
    offset: int = Query(default=0, ge=0),
) -> ObservationHistoryResponse:
    """Every review attempt LensWord has recorded evidence for, newest
    first — including ones already flagged, which a diagnosis rebuild no
    longer sees but the learner who flagged them still should."""
    rows = observation_repo.list_for_user(current_user.id, limit=limit + 1, offset=offset)
    has_more = len(rows) > limit
    rows = rows[:limit]

    corrections = observation_repo.corrections_for(current_user.id, [r.observation_id for r in rows])

    # Resolved per unique word id actually on this page, the same
    # bounded-lookup shape weaknesses.py already uses for confused-pair terms.
    terms: dict[int, str | None] = {}
    for row in rows:
        if row.word_id not in terms:
            word = word_repo.get_by_id(row.word_id)
            terms[row.word_id] = word.term if word else None

    return ObservationHistoryResponse(
        items=[
            ObservationHistoryItem(
                observation_id=row.observation_id,
                word_id=row.word_id,
                word_term=terms.get(row.word_id),
                outcome=row.outcome.value,
                session_mode=row.session_mode.value,
                observed_at=row.observed_at,
                attempted_answer=row.attempted_answer,
                modality=row.modality,
                hint_used=row.hint_used,
                correction=_correction_response(corrections.get(row.observation_id)),
            )
            for row in rows
        ],
        has_more=has_more,
    )


@router.post(
    "/observations/{observation_id}/correct",
    response_model=ObservationCorrectionResponse,
    status_code=status.HTTP_201_CREATED,
)
def correct_observation(
    observation_id: str,
    payload: CorrectObservationRequest,
    current_user: CurrentUser,
    observation_repo: LearningObservationRepo,
) -> ObservationCorrectionResponse:
    """Flag one recorded observation as misgraded or irrelevant. The
    observation itself is never touched (issue #229 TODO 5's append-only
    requirement) — this adds a new row naming it, which the five
    diagnosis-facing queries in `LearningObservationRepository` then
    exclude it by.
    """
    observation: LearningObservation | None = observation_repo.get_by_id(current_user.id, observation_id)
    if observation is None:
        # 404 whether the observation is missing or belongs to someone
        # else, matching diagnosis.py/graph.py's existing tenant-isolation
        # pattern — a distinguishable 403 would confirm the id exists to
        # an account that does not own it.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Observation not found")

    if observation_repo.correction_for(current_user.id, observation_id) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This observation has already been flagged")

    correction = ObservationCorrection(
        correction_id=uuid.uuid4().hex,
        observation_id=observation_id,
        user_id=current_user.id,
        reason=payload.reason,
        note=payload.note,
        created_at=utcnow(),
    )
    saved = observation_repo.add_correction(correction)
    return ObservationCorrectionResponse(
        correction_id=saved.correction_id, reason=saved.reason, note=saved.note, created_at=saved.created_at
    )
