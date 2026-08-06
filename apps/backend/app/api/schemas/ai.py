from typing import Literal

from pydantic import BaseModel, Field


class EnrichWordRequest(BaseModel):
    term: str = Field(min_length=1, max_length=255)
    source_language: str | None = Field(default=None, max_length=32)
    target_language: str = Field(min_length=1, max_length=32)


class WordEnrichmentResponse(BaseModel):
    term: str
    target_language: str
    translations: list[str]
    definitions: list[str]
    part_of_speech: str | None
    cefr_level: str | None
    pronunciation: str | None
    examples: list[str]
    synonyms: list[str]
    antonyms: list[str]
    collocations: list[str]
    tags: list[str]
    topics: list[str]
    mnemonic: str | None
    category: str | None
    confidence: float | None
    provider: str
    model: str


class TranslateInContextRequest(BaseModel):
    word: str = Field(min_length=1, max_length=255)
    sentence: str = Field(min_length=1, max_length=4_000)
    source_language: str | None = Field(default=None, max_length=32)
    target_language: str = Field(min_length=1, max_length=32)


class GenerateExamplesRequest(EnrichWordRequest):
    interests: str | None = Field(default=None, max_length=256)
    profession: str | None = Field(default=None, max_length=128)
    topic: str | None = Field(default=None, max_length=128)


class RegenerateFieldRequest(EnrichWordRequest):
    field: Literal["example", "mnemonic", "definition", "translation"]
    context: str | None = Field(default=None, max_length=4_000)


class RegeneratedFieldResponse(BaseModel):
    field: str
    value: str
