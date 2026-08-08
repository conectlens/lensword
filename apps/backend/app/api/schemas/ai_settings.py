from pydantic import BaseModel, Field, HttpUrl


class AISettingsResponse(BaseModel):
    provider: str
    # Ollama-shaped fields — kept as their original names for backwards
    # compatibility with every existing caller of this endpoint.
    model: str
    base_url: str
    max_output_tokens: int
    context_max_chars: int
    # Cloud provider fields (issue #315). Each provider's model name is
    # reported directly (not a secret); each provider's credential is
    # reported only as "is one configured" — never the key value itself,
    # the same "report presence, not the secret" shape many admin APIs use
    # for a stored credential.
    gemini_model: str
    gemini_api_key_set: bool
    vertex_project_id: str | None
    vertex_location: str
    vertex_model: str
    openai_model: str
    openai_api_key_set: bool


class AISettingsUpdateRequest(BaseModel):
    provider: str = Field(min_length=1, max_length=32)
    model: str = Field(min_length=1, max_length=255)
    base_url: HttpUrl
    max_output_tokens: int = Field(gt=0, le=4_000)
    context_max_chars: int = Field(gt=0, le=20_000)
    # Every cloud field below is optional on the wire: a PUT that switches
    # to (or stays on) Ollama has no reason to carry any of them, and a PUT
    # that updates a cloud provider's model/project without touching its
    # secret sends a blank key on purpose — see
    # app.config.save_effective_ai_settings for what a blank key means.
    gemini_api_key: str | None = Field(default=None, max_length=512)
    gemini_model: str = Field(default="gemini-2.5-flash", min_length=1, max_length=255)
    vertex_project_id: str | None = Field(default=None, max_length=255)
    vertex_location: str = Field(default="us-central1", min_length=1, max_length=64)
    vertex_model: str = Field(default="gemini-2.5-flash", min_length=1, max_length=255)
    openai_api_key: str | None = Field(default=None, max_length=512)
    openai_model: str = Field(default="gpt-5.6-luna", min_length=1, max_length=255)


class AIProbeResponse(BaseModel):
    """What a detection step found for the *currently configured* provider,
    and what to do about it (issue #139, generalized by #315).

    Ollama gets the original reachability + model-list check
    (`live_check_performed=True`); a cloud provider gets a
    configuration-completeness check instead — no live call, see
    `probe()` in `app/api/routers/ai_settings.py` for why — so
    `live_check_performed=False` there tells a caller not to read
    `reachable`/`ready` as "verified against the real API", only as
    "the required credential looks configured".
    """

    provider: str
    live_check_performed: bool
    reachable: bool
    # True only when the configured model is actually installed/usable.
    # Reachable is not the same as usable.
    ready: bool
    models: list[str]
    configured_model: str | None
    configured_model_installed: bool
    recommended_model: str
    # A sentence written for the person reading it. Composed server-side so
    # the reason and the advice cannot drift apart.
    detail: str


# Backwards-compatible alias: this response shape used to be Ollama-only and
# named accordingly. Kept so nothing importing the old name breaks.
OllamaProbeResponse = AIProbeResponse
