"""Knowledge-graph search and CEFR progress responses (issue #143)."""
from pydantic import BaseModel


class RelatedWordResponse(BaseModel):
    word_id: int
    term: str
    relation: str
    strength: float
    # Why the two are related, in words. Carried so the client can justify an
    # edge rather than only assert it — a graph that cannot explain itself is
    # one nobody trusts enough to act on.
    evidence: str


class PrerequisitesResponse(BaseModel):
    word_id: int
    term: str
    cefr_level: str | None
    prerequisites: list[RelatedWordResponse]
    # Set when the word's own level is unknown, so no comparison is possible.
    # Distinguished from "nothing easier found", which is a real answer.
    level_unknown: bool


class LevelProgressResponse(BaseModel):
    level: str
    total: int
    started: int
    mastered: int
    mastery_share: float


class CefrProgressResponse(BaseModel):
    levels: list[LevelProgressResponse]
    # Words with no CEFR level recorded, reported on their own so the parts
    # still add up to the learner's actual word count.
    unlevelled: LevelProgressResponse | None
    total_words: int
