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


class OllamaProbeResponse(BaseModel):
    """What a detection step found, and what to do about it (issue #139)."""

    reachable: bool
    # True only when the configured model is actually installed. Reachable is
    # not the same as usable.
    ready: bool
    models: list[str]
    configured_model: str | None
    configured_model_installed: bool
    recommended_model: str
    # A sentence written for the person reading it. Composed server-side so the
    # reason and the advice cannot drift apart.
    detail: str
