from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

SUPPORTED_AI_PROVIDERS = ("none", "ollama")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "LensWord API"
    environment: str = "development"

    database_url: str = "sqlite:///./data/lensword.db"

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
