from functools import lru_cache
import json
from pathlib import Path
from tempfile import NamedTemporaryFile

from pydantic import BaseModel, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

SUPPORTED_AI_PROVIDERS = ("none", "ollama")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "LensWord API"
    environment: str = "development"

    # SQLite remains the default so a fresh checkout runs with no database
    # server to install. Postgres is the supported deployment target (ROADMAP
    # 4.0) and is what docker-compose starts; point this at
    # `postgresql+psycopg://user:pass@host:5432/db` to use it.
    database_url: str = "sqlite:///./data/lensword.db"

    # Connection-pool bounds. Ignored on SQLite, which has no server-side
    # connection to budget. The defaults are deliberately modest: a managed
    # Postgres plan's connection cap is shared across every running instance,
    # so the ceiling that matters is pool_size + max_overflow multiplied by
    # the instance count.
    db_pool_size: int = 5
    db_max_overflow: int = 10

    secret_key: str = "change-me-in-production-this-is-not-secure"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24 * 7  # 7 days

    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:3000", "http://localhost:8080"]

    first_admin_email: str | None = None
    first_admin_password: str | None = None

    # AI provider. "none" (the default) builds no provider at all, so an
    # existing deployment that sets none of these boots and behaves exactly
    # as it did before. Set AI_PROVIDER=ollama to enable local suggestions.
    ai_provider: str = "none"
    ollama_model: str = "llama3.2"
    ollama_base_url: str = "http://localhost:11434"

    # Bounds on one suggestion. A mnemonic is a sentence, so the token limit
    # is generous for the intended output while still keeping a steered model
    # from returning an unbounded response body (issue #45).
    ai_max_output_tokens: int = 200
    ai_context_max_chars: int = 500
    # Test/demo-only escape hatch. Production stays honest when AI is disabled:
    # it reports that state instead of presenting heuristic output as AI work.
    ai_extract_fallback_enabled: bool = False
    ai_settings_path: str = "data/ai-settings.json"

    @field_validator("db_pool_size", "db_max_overflow")
    @classmethod
    def _non_negative_pool_bound(cls, value: int) -> int:
        """A negative bound is accepted by SQLAlchemy as 'unbounded', which for
        a shared Postgres connection cap is the opposite of what setting it is
        for. Fail at startup rather than under load."""
        if value < 0:
            raise ValueError(f"must be 0 or greater (got {value})")
        return value

    @field_validator("ai_max_output_tokens", "ai_context_max_chars")
    @classmethod
    def _positive_bound(cls, value: int) -> int:
        """A non-positive bound would either truncate every record to nothing
        or, for num_predict, be read by Ollama as 'no limit' — the opposite of
        what setting it is for. Fail at startup rather than at generation."""
        if value <= 0:
            raise ValueError(f"must be greater than 0 (got {value})")
        return value

    @field_validator("ai_provider")
    @classmethod
    def _known_ai_provider(cls, value: str) -> str:
        """Reject a typo while the operator is still watching the console.

        Validating here rather than only in the factory means a misspelled
        AI_PROVIDER stops startup outright, instead of lying dormant until
        someone's first suggestion request turns it into a 500.
        """
        normalized = value.strip().lower()
        if normalized not in SUPPORTED_AI_PROVIDERS:
            raise ValueError(
                f"must be one of {', '.join(SUPPORTED_AI_PROVIDERS)} (got '{value}')"
            )
        return normalized


@lru_cache
def get_settings() -> Settings:
    return Settings()


_AI_OVERRIDE_FIELDS = (
    "ai_provider",
    "ollama_model",
    "ollama_base_url",
    "ai_max_output_tokens",
    "ai_context_max_chars",
)


class AISettingsUpdate(BaseModel):
    ai_provider: str
    ollama_model: str
    ollama_base_url: str
    ai_max_output_tokens: int
    ai_context_max_chars: int


def _runtime_override_path(settings: Settings) -> Path:
    return Path(settings.ai_settings_path)


def get_effective_ai_settings() -> Settings:
    """Return environment defaults overlaid by validated admin configuration."""
    base = get_settings()
    path = _runtime_override_path(base)
    if not path.exists():
        return base
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"AI settings override at {path} is unreadable") from exc
    if not isinstance(raw, dict):
        raise RuntimeError(f"AI settings override at {path} must be a JSON object")
    override = {name: raw[name] for name in _AI_OVERRIDE_FIELDS if name in raw}
    return Settings(**(base.model_dump() | override))


def save_effective_ai_settings(update: AISettingsUpdate) -> Settings:
    """Validate and atomically persist the deployment-wide AI configuration."""
    base = get_settings()
    values = update.model_dump()
    if not values["ollama_model"].strip():
        raise ValueError("ollama_model must not be blank")
    if not values["ollama_base_url"].strip():
        raise ValueError("ollama_base_url must not be blank")
    validated = Settings(**(base.model_dump() | values))
    path = _runtime_override_path(base)
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as temporary:
        json.dump({field: getattr(validated, field) for field in _AI_OVERRIDE_FIELDS}, temporary)
        temporary.write("\n")
        temporary_path = Path(temporary.name)
    temporary_path.replace(path)
    return validated
