from datetime import datetime

from pydantic import BaseModel, Field

from app.domain.value_objects import SupportedLanguage, WordStatus


class GroupCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    target_language: SupportedLanguage


class GroupRenameRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)


class GroupResponse(BaseModel):
    id: int
    name: str
    target_language: SupportedLanguage
    created_at: datetime
    word_count: int
    mastered_count: int
    due_count: int
    last_reviewed_at: datetime | None


class ReviewStateResponse(BaseModel):
    strength: int
    ease_factor: float
    interval_days: float
    repetitions: int
    due_at: datetime
    last_reviewed_at: datetime | None
    status: WordStatus
    fsrs_retrievability: float | None = None


class WordResponse(BaseModel):
    id: int
    group_id: int
    term: str
    target_language: SupportedLanguage
    translations: list[str]
    example_sentence: str | None
    mnemonic: str | None
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
    # "human", "unverified" or "verified" (#140). Derived rather than stored so
    # the badge cannot disagree with the provenance columns it describes.
    ai_state: str = "human"
    synonyms: list[str]
    antonyms: list[str]
    topics: list[str]
    review_state: ReviewStateResponse
    created_at: datetime
    # What an offline edit must name as base_revision to reconcile without a
    # conflict later (issue #90).
    revision: int


class WordCreateRequest(BaseModel):
    term: str = Field(min_length=1, max_length=255)
    target_language: SupportedLanguage
    translations: list[str] = Field(default_factory=list)
    example_sentence: str | None = None
    mnemonic: str | None = None
    category: str | None = None
    definition: str | None = None
    part_of_speech: str | None = Field(default=None, max_length=64)
    cefr_level: str | None = Field(default=None, max_length=8)
    pronunciation: str | None = Field(default=None, max_length=255)
    collocations: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    ai_confidence: float | None = Field(default=None, ge=0, le=1)
    ai_provider: str | None = Field(default=None, max_length=64)
    ai_model: str | None = Field(default=None, max_length=255)


class WordAssociationEdit(BaseModel):
    kind: str = Field(pattern="^(synonym|antonym|topic)$")
    value: str = Field(min_length=1, max_length=64)


class WordAssociationsUpdateRequest(BaseModel):
    add: list[WordAssociationEdit] = Field(default_factory=list)
    remove: list[WordAssociationEdit] = Field(default_factory=list)


class RoomCreateRequest(BaseModel):
    group_id: int
    name: str = Field(min_length=1, max_length=128)
    icon: str = "meeting_room"


class RoomPlacementResponse(BaseModel):
    word_id: int
    x_percent: float
    y_percent: float
    placed_at: datetime


class RoomResponse(BaseModel):
    id: int
    group_id: int
    name: str
    icon: str
    created_at: datetime
    placements: list[RoomPlacementResponse]
    group_word_count: int

    @property
    def words_placed(self) -> int:
        return len(self.placements)


class PlaceWordRequest(BaseModel):
    word_id: int
    x_percent: float = Field(ge=0, le=100)
    y_percent: float = Field(ge=0, le=100)


class WordRevisionResponse(BaseModel):
    """One AI-authored field changing value (issue #140)."""

    field: str
    # Null means the field had no value before — "the model added this" rather
    # than "the model replaced this".
    before_value: str | None
    after_value: str | None
    # "ai", "human" or "bulk". Recorded when the change was made; after the
    # fact there is no way to tell them apart.
    source: str
    changed_at: datetime


class WordVerificationResponse(BaseModel):
    word_id: int
    # "human", "unverified" or "verified". Three states rather than two,
    # because "written by a model and checked" and "written by a person" are
    # different facts and collapsing them would hide which cards were ever
    # machine-written.
    state: str
    ai_verified_at: datetime | None


class BulkWordEditRequest(BaseModel):
    """Apply the same field values to several words at once (issue #140).

    Only fields a bulk edit can sensibly set are here. Term and translations
    are excluded on purpose: those are what makes a card that card, and a bulk
    control that could overwrite forty terms with one value is a mistake
    waiting to be made irreversibly.
    """

    word_ids: list[int] = Field(min_length=1, max_length=200)
    cefr_level: str | None = Field(default=None, max_length=8)
    part_of_speech: str | None = Field(default=None, max_length=64)
    category: str | None = None
    tags: list[str] | None = None


class BulkWordEditResponse(BaseModel):
    updated: int
    # Ids that were skipped because they are not this account's. Reported
    # rather than silently dropped: a bulk edit that quietly did less than it
    # was asked is worse than one that says so.
    skipped: list[int]
