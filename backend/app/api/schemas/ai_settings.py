from pydantic import BaseModel, Field, HttpUrl


class AISettingsResponse(BaseModel):
    provider: str
    model: str
    base_url: str
    max_output_tokens: int
    context_max_chars: int


class AISettingsUpdateRequest(BaseModel):
    provider: str = Field(min_length=1, max_length=32)
    model: str = Field(min_length=1, max_length=255)
    base_url: HttpUrl
    max_output_tokens: int = Field(gt=0, le=4_000)
    context_max_chars: int = Field(gt=0, le=20_000)
