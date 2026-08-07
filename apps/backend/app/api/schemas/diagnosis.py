"""Deterministic diagnosis responses (#180, issue #183)."""
from datetime import datetime

from pydantic import BaseModel


class DiagnosisEvidenceResponse(BaseModel):
    kind: str
    observation_ids: list[str]
    weight: float
    description: str


class DiagnosisResponse(BaseModel):
    word_id: int
    outcome: str
    evidence: list[DiagnosisEvidenceResponse]
    # None only for UNKNOWN/INSUFFICIENT_EVIDENCE — an abstention has no
    # confidence to report, not a fabricated 0.0 (see Diagnosis.is_abstention).
    confidence: float | None
    rules_version: int
    diagnosed_at: datetime
    sample_size: int
    competing_hypotheses: list[str]
    is_abstention: bool


class DiagnosisListResponse(BaseModel):
    """Issue #192's `/me/diagnoses` companion resource — every diagnosis
    across the account's whole vocabulary, not one word. Bounded and
    paginated with a real offset cursor: `next_cursor` is non-null only
    when a further page genuinely exists, the same honesty
    `ObservationHistoryResponse.has_more` already provides for observation
    history, expressed as a cursor rather than a flag to match the MCP
    resource shape this response backs.
    """

    items: list[DiagnosisResponse]
    next_cursor: str | None = None
