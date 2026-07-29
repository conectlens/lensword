from typing import Annotated, Literal

from pydantic import BaseModel, Field


class ExtractVocabularyRequest(BaseModel):
    group_id: int = Field(gt=0)
    text: str = Field(min_length=1, max_length=20_000)
    source_language: str | None = Field(default=None, max_length=32)
    target_language: str = Field(min_length=1, max_length=32)
    max_items: int = Field(default=10, ge=1, le=50)


class ExtractedVocabularyResponse(BaseModel):
    term: str
    translations: list[str]
    examples: list[str]


class ExtractVocabularyOk(BaseModel):
    status: Literal["ok"] = "ok"
    source: Literal["ai", "fallback"]
    items: list[ExtractedVocabularyResponse]


class ExtractVocabularyDisabled(BaseModel):
    status: Literal["disabled"] = "disabled"


class ExtractVocabularyUnavailable(BaseModel):
    status: Literal["unavailable"] = "unavailable"
    detail: str


ExtractVocabularyResponse = Annotated[
    ExtractVocabularyOk | ExtractVocabularyDisabled | ExtractVocabularyUnavailable,
    Field(discriminator="status"),
]
