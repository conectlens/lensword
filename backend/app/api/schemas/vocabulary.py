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


class WordResponse(BaseModel):
    id: int
    group_id: int
    term: str
    target_language: SupportedLanguage
    translations: list[str]
    example_sentence: str | None
    mnemonic: str | None
    category: str | None
    synonyms: list[str]
    antonyms: list[str]
    topics: list[str]
    review_state: ReviewStateResponse
    created_at: datetime


class WordCreateRequest(BaseModel):
    term: str = Field(min_length=1, max_length=255)
    target_language: SupportedLanguage
    translations: list[str] = Field(default_factory=list)
    example_sentence: str | None = None
    mnemonic: str | None = None
    category: str | None = None


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
