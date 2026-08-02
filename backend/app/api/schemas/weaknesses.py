"""Weakness profile responses (issue #134).

Every figure carries the count it was derived from. A share on its own invites
the reader to treat 60% of five mistakes and 60% of five hundred as the same
claim, and the whole point of this feature is not to overstate what we know.
"""
from pydantic import BaseModel


class CategoryWeaknessResponse(BaseModel):
    category: str
    occurrences: int
    # Share of all this learner's recorded mistakes, 0..1.
    share: float


class ConfusedPairResponse(BaseModel):
    word_id: int
    word_term: str | None = None
    confused_with_word_id: int
    confused_with_term: str | None = None
    occurrences: int


class WeaknessProfileResponse(BaseModel):
    total_mistakes: int
    categories: list[CategoryWeaknessResponse]
    confused_pairs: list[ConfusedPairResponse]
    # True when there is not enough history to say anything. The client shows
    # this rather than an empty profile, which reads as "you have no
    # weaknesses" instead of "we do not know yet".
    insufficient_data: bool
