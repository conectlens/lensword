"""Weakness profile responses (issue #134).

Every figure carries the count it was derived from. A share on its own invites
the reader to treat 60% of five mistakes and 60% of five hundred as the same
claim, and the whole point of this feature is not to overstate what we know.

`generated_at` and `evidence_ids` (issue #192 TODO 0: "include a freshness
timestamp" / "evidence/provenance IDs for claims") mirror the pattern
`DiagnosisResponse` already established for the same requirement — a
diagnosis names the `observation_ids` behind it and the moment it was
produced, and a weakness claim is exactly the same kind of claim.
"""
from datetime import datetime

from pydantic import BaseModel


class CategoryWeaknessResponse(BaseModel):
    category: str
    occurrences: int
    # Share of all this learner's recorded mistakes, 0..1.
    share: float
    # The `mistake_events` row ids this count was derived from, bounded and
    # newest first. Empty rather than absent when there is nothing to name,
    # so a client does not have to distinguish "not implemented" from
    # "no evidence ids for this claim".
    evidence_ids: list[int] = []


class ConfusedPairResponse(BaseModel):
    word_id: int
    word_term: str | None = None
    confused_with_word_id: int
    confused_with_term: str | None = None
    occurrences: int
    evidence_ids: list[int] = []


class RelationErrorCountResponse(BaseModel):
    relation: str
    occurrences: int


class CrossAssociationReportResponse(BaseModel):
    """Issue #207 TODO 0: how often a wrong answer named a word already known
    to be semantically related to the target, segmented by relation type."""

    resolved_errors: int
    related_errors: int
    error_rate: float
    by_relation: list[RelationErrorCountResponse]
    # True when there are too few resolved errors to report a rate without
    # it being noise dressed up as a finding.
    insufficient_data: bool


class WeaknessProfileResponse(BaseModel):
    total_mistakes: int
    categories: list[CategoryWeaknessResponse]
    confused_pairs: list[ConfusedPairResponse]
    cross_association: CrossAssociationReportResponse
    # When this profile was computed, not when any individual mistake
    # happened — a companion reading this resource needs to know how stale
    # the aggregate itself is (issue #192 TODO 0).
    generated_at: datetime
    # True when there is not enough history to say anything. The client shows
    # this rather than an empty profile, which reads as "you have no
    # weaknesses" instead of "we do not know yet".
    insufficient_data: bool
