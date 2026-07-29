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


class ImportPreviewResponse(BaseModel):
    records: list[ImportPreviewRecord]


class ImportCommitRequest(BaseModel):
    group_id: int = Field(gt=0)
    records: list[ImportPreviewRecord] = Field(min_length=1, max_length=500)


class ImportParseResponse(BaseModel):
    records: list[ImportRecordRequest]
