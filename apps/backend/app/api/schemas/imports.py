from typing import Literal
from pydantic import BaseModel, Field

from app.api.schemas.ai import WordEnrichmentResponse


class ImportRecordRequest(BaseModel):
    term: str = Field(min_length=1, max_length=255)
    translations: list[str] = Field(default_factory=list)
    definition: str | None = None
    part_of_speech: str | None = None
    cefr_level: str | None = None
    pronunciation: str | None = None


class ImportPreviewRequest(BaseModel):
    group_id: int = Field(gt=0)
    records: list[ImportRecordRequest] = Field(min_length=1, max_length=500)
    source_language: str | None = Field(default=None, max_length=32)
    enrich_with_ai: bool = False


class ImportPreviewRecord(BaseModel):
    term: str
    translations: list[str]
    definition: str | None
    part_of_speech: str | None
    cefr_level: str | None
    pronunciation: str | None
    source_language: str
    status: Literal['ready', 'ai_cleaned', 'duplicate']
    duplicate_of: str | None = None
    provider: str | None = None
    model: str | None = None
    # AI-only: a raw parsed row never has these (issue #202 TODO 3). Empty
    # unless enrichment actually ran.
    synonyms: list[str] = Field(default_factory=list)
    antonyms: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    # Set only when issue #204's diversity policy pushed this record later
    # in the order because it overlaps vocabulary the account already
    # studies — the one case with an unambiguous, learner-facing "why".
    deferred_reason: str | None = None


class ImportPreviewResponse(BaseModel):
    records: list[ImportPreviewRecord]
    # Whether issue #204's semantic-diversity policy reordered `records`
    # from the request's original order. False whenever the flag is off or
    # nothing in the batch was related enough to move.
    diversity_ordering_applied: bool = False


class ImportCommitRequest(BaseModel):
    group_id: int = Field(gt=0)
    records: list[ImportPreviewRecord] = Field(min_length=1, max_length=500)


class ImportParseResponse(BaseModel):
    records: list[ImportRecordRequest]


class ImportUrlRequest(BaseModel):
    """A page to fetch and parse (issue #145).

    A plain string rather than pydantic's `AnyHttpUrl`: the real validation is
    in `app.domain.services.url_safety`, which also has to resolve the host,
    and having two validators disagree about what a URL is would mean one of
    them is decorative.
    """

    url: str
