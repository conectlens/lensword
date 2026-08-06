"""Deterministic diagnosis endpoints (#180, issue #183 TODO 5).

Latest diagnosis and diagnosis history only. Evidence-inspection detail
and learner feedback (flag as misgraded) are split into #229 alongside
#182's own deferred learner-facing debugging view — the same reasoning:
a full new UI+API surface, not an extension of what ships here.
"""
from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUser, DiagnosisRepo, WordRepo
from app.api.schemas.diagnosis import DiagnosisEvidenceResponse, DiagnosisResponse
from app.domain.services.diagnosis_contracts import Diagnosis

router = APIRouter(prefix="/api/v1/words", tags=["diagnosis"])


def _response(d: Diagnosis) -> DiagnosisResponse:
    return DiagnosisResponse(
        word_id=d.word_id,
        outcome=d.outcome,
        evidence=[
            DiagnosisEvidenceResponse(
                kind=e.kind, observation_ids=list(e.observation_ids), weight=e.weight, description=e.description
            )
            for e in d.evidence
        ],
        confidence=d.confidence,
        rules_version=d.rules_version,
        diagnosed_at=d.diagnosed_at,
        sample_size=d.sample_size,
        competing_hypotheses=list(d.competing_hypotheses),
        is_abstention=d.is_abstention,
    )


def _require_owned_word(word_repo: WordRepo, user_id: int, word_id: int):
    words = word_repo.list_all_for_user(user_id)
    word = next((w for w in words if w.id == word_id), None)
    if word is None:
        # 404 whether the word is missing or belongs to someone else,
        # matching graph.py's existing tenant-isolation pattern — a
        # distinguishable 403 would confirm the id exists to an account
        # that does not own it.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Word not found")
    return word


@router.get("/{word_id}/diagnosis", response_model=DiagnosisResponse | None)
def latest_diagnosis(word_id: int, current_user: CurrentUser, word_repo: WordRepo, diagnosis_repo: DiagnosisRepo):
    """The most recent diagnosis for this word, or null if none has ever
    been produced — a word with no failures, or an account with diagnosis
    disabled, both look like this rather than an error."""
    _require_owned_word(word_repo, current_user.id, word_id)
    latest = diagnosis_repo.latest_for_word(current_user.id, word_id)
    return _response(latest) if latest is not None else None


@router.get("/{word_id}/diagnosis/history", response_model=list[DiagnosisResponse])
def diagnosis_history(
    word_id: int, current_user: CurrentUser, word_repo: WordRepo, diagnosis_repo: DiagnosisRepo, limit: int = 50
):
    """Every diagnosis ever produced for this word, newest first —
    append-only, so a corrected diagnosis is visible alongside the
    original it corrected rather than replacing it."""
    _require_owned_word(word_repo, current_user.id, word_id)
    return [_response(d) for d in diagnosis_repo.list_for_word(current_user.id, word_id, limit)]
