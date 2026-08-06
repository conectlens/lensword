"""Learner-facing observation history and correction responses (#180, issue #229 TODO 5)."""
from datetime import datetime

from pydantic import BaseModel, Field

from app.domain.services.diagnosis_contracts import ObservationCorrectionReason


class ObservationCorrectionResponse(BaseModel):
    correction_id: str
    reason: ObservationCorrectionReason
    note: str | None
    created_at: datetime


class ObservationHistoryItem(BaseModel):
    observation_id: str
    word_id: int
    # Null for a word that has since been deleted — the observation still
    # happened and still counts as evidence history, the same reasoning
    # WeaknessProfileResponse already applies to a deleted confused-with word.
    word_term: str | None
    outcome: str
    session_mode: str
    observed_at: datetime
    attempted_answer: str | None
    modality: str | None
    hint_used: bool
    # Present once this observation has been flagged (issue #229 TODO 5) —
    # still shown here even though a flagged observation stops appearing
    # as diagnosis evidence, because a learner reviewing their own history
    # needs to see what they already flagged.
    correction: ObservationCorrectionResponse | None


class ObservationHistoryResponse(BaseModel):
    items: list[ObservationHistoryItem]
    has_more: bool


class CorrectObservationRequest(BaseModel):
    reason: ObservationCorrectionReason
    note: str | None = Field(default=None, max_length=500)
