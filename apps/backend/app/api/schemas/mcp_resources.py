"""Response projections for the MCP-facing companion surface (issue #192).

A companion resource is not the same audience as the REST API. The API
returns a learner's own data to the learner's own client, unredacted,
because it is theirs (`sync.py`'s `export_unsynced` reasons about this same
distinction for a different endpoint). An AI companion acting through MCP is
a third party the learner has opted into, and TODO 0 is explicit about the
boundary: "redact raw answers, private mnemonics, and source context by
default."

`CompanionWordView` is that redaction, built the same way
`diagnosis_events.py` builds its observability events: the sensitive field
has no place on the type at all, so a caller reaching for `.mnemonic` gets an
`AttributeError` rather than relying on every call site remembering to strip
a key after the fact. A stripped-after-the-fact filter is exactly the shape
of bug that shipped here originally — `bindings.py` called the REST mapper
(`word_to_response`, which includes `mnemonic`) directly and handed the
result to an MCP resource without redacting anything.
"""
from datetime import datetime

from pydantic import BaseModel

from app.api.schemas.vocabulary import ReviewStateResponse
from app.domain.value_objects import SupportedLanguage


class CompanionWordView(BaseModel):
    """Everything an AI companion may see about one word through MCP —
    `WordResponse` minus the fields TODO 0 names as private (`mnemonic`) and
    minus session-only state that never applies to a resource listing
    (`mcq_options`). Kept as its own model instead of
    `WordResponse.model_dump(exclude={...})` so a field added to
    `WordResponse` later defaults to *absent* from the companion surface
    until someone deliberately adds it here, rather than leaking silently
    until someone remembers to extend an exclude list.
    """

    id: int
    group_id: int
    term: str
    target_language: SupportedLanguage
    translations: list[str]
    example_sentence: str | None
    category: str | None
    definition: str | None
    part_of_speech: str | None
    cefr_level: str | None
    pronunciation: str | None
    collocations: list[str]
    tags: list[str]
    ai_confidence: float | None
    ai_provider: str | None
    ai_model: str | None
    ai_verified_at: datetime | None = None
    ai_state: str = "human"
    synonyms: list[str]
    antonyms: list[str]
    topics: list[str]
    review_state: ReviewStateResponse
    created_at: datetime
    revision: int


class CompanionWordPageResponse(BaseModel):
    """A bounded, paginated page of `CompanionWordView`s — the shape both
    `/me/active-words` and `/me/due` return. `next_cursor` is an opaque
    offset token: present and non-null only when there is a further page to
    ask for, absent (`None`) once the caller has reached the end.
    """

    items: list[CompanionWordView]
    next_cursor: str | None = None
