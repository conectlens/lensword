from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


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


@lru_cache
def get_settings() -> Settings:
    return Settings()
