from functools import lru_cache
import json
from pathlib import Path
from tempfile import NamedTemporaryFile

from pydantic import BaseModel, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Matches app/infrastructure/ai_providers/factory.py's own tuple, kept in
# sync by hand rather than imported — see that module's docstring for why
# the duplication is deliberate (a circular import otherwise).
SUPPORTED_AI_PROVIDERS = ("none", "ollama", "gemini", "vertex", "openai")
SUPPORTED_JOB_STORES = ("database", "memory")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "LensWord API"
    environment: str = "development"

    # Root logger level. INFO in development gives request/scheduler visibility
    # without SQL noise; DEBUG additionally requires db_echo below to see queries.
    log_level: str = "INFO"

    # SQLite remains the default so a fresh checkout runs with no database
    # server to install. Postgres is the supported deployment target (ROADMAP
    # 4.0) and is what docker-compose starts; point this at
    # `postgresql+psycopg://user:pass@host:5432/db` to use it.
    database_url: str = "sqlite:///./data/lensword.db"
    # Echoes every SQL statement SQLAlchemy issues to the log. Off by default —
    # even at DEBUG log level — since it's noisy; opt in per-session when
    # tracking down a query.
    db_echo: bool = False

    # Connection-pool bounds. Ignored on SQLite, which has no server-side
    # connection to budget. The defaults are deliberately modest: a managed
    # Postgres plan's connection cap is shared across every running instance,
    # so the ceiling that matters is pool_size + max_overflow multiplied by
    # the instance count.
    db_pool_size: int = 5
    db_max_overflow: int = 10

    # Where scheduled jobs live (ROADMAP 4.2). "database" persists them in the
    # configured database so they survive a restart; "memory" keeps the old
    # in-process behaviour, which is what the test suite and any single-shot
    # process want. Persistence alone does not make firing exclusive — see
    # app.infrastructure.job_claims for that half.
    scheduler_job_store: str = "database"

    secret_key: str = "change-me-in-production-this-is-not-secure"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24 * 7  # 7 days

    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:3000", "http://localhost:8080"]

    first_admin_email: str | None = None
    first_admin_password: str | None = None

    # AI provider. "none" (the default) builds no provider at all, so an
    # existing deployment that sets none of these boots and behaves exactly
    # as it did before. Set AI_PROVIDER=ollama to enable local suggestions,
    # or one of "gemini"/"vertex"/"openai" (issue #315) for a hosted deploy
    # that cannot run its own Ollama daemon (e.g. Render — see
    # docs/internal/render-deployment.md).
    ai_provider: str = "none"
    ollama_model: str = "llama3.2"
    ollama_base_url: str = "http://localhost:11434"

    # Gemini Developer API (issue #315) — a single API key from
    # https://aistudio.google.com/apikey. None by default: an operator who
    # never sets AI_PROVIDER=gemini never needs one, and build_ai_provider
    # raises a clear startup error naming this field if they do without
    # setting it, rather than a confusing failure on first request.
    gemini_api_key: str | None = None
    # gemini-2.5-flash: the fast/economical Gemini tier — a sensible default
    # for a feature (mnemonic suggestions, vocabulary enrichment) that runs
    # on every learner action, not the top-of-line reasoning model.
    gemini_model: str = "gemini-2.5-flash"

    # Google Vertex AI (issue #315) — the same google-genai SDK as Gemini
    # above, but authenticated via Application Default Credentials rather
    # than an API key (a GCP service-account key file referenced by
    # GOOGLE_APPLICATION_CREDENTIALS, or workload identity), which is why
    # there is no vertex_api_key field here: ADC is the SDK's own concern,
    # configured in the deploy environment, not read through Settings.
    vertex_project_id: str | None = None
    # us-central1: one of Vertex AI's original, widely available regions for
    # Gemini models — a reasonable default for an operator who has not yet
    # thought about where their GCP project's data should live.
    vertex_location: str = "us-central1"
    vertex_model: str = "gemini-2.5-flash"

    # OpenAI (issue #315) — a single API key from
    # https://platform.openai.com/api-keys.
    openai_api_key: str | None = None
    # gpt-5.6-luna: OpenAI's cost-optimized tier, confirmed via the OpenAI
    # API documentation (developers.openai.com) while this adapter was
    # built — matching gemini_model's own reasoning above: this runs on
    # every learner action, so the default should be the cheap/fast tier
    # (gpt-5.6-sol/-terra are the more expensive reasoning/balanced tiers a
    # deployment can opt into via OPENAI_MODEL). Model names churn faster
    # than most dependencies, so this is worth re-checking against the live
    # model list before a production deploy rather than trusted indefinitely.
    openai_model: str = "gpt-5.6-luna"

    # Bounds on one generation. Still keeps a steered model from returning an
    # unbounded response body (issue #45), but 200 — sized only for a
    # mnemonic's one sentence — cut every structured-JSON response (an
    # enrichment, a conversation turn with corrections, a learning-path
    # milestone list) off mid-string well before its closing brace, which
    # then failed to parse and surfaced as a misleading "provider
    # unreachable" (issue #211). `num_predict` is a ceiling, not a target
    # length — raising it does not make a short plain-text reply any
    # longer, since the model still stops on its own once it's actually
    # done. 900 is empirically verified (issues #211/#212/#213/#214) to
    # clear every structured shape this codebase asks for, including the
    # largest one (an 8-milestone learning path).
    ai_max_output_tokens: int = 900
    ai_context_max_chars: int = 500
    # Test/demo-only escape hatch. Production stays honest when AI is disabled:
    # it reports that state instead of presenting heuristic output as AI work.
    ai_extract_fallback_enabled: bool = False
    ai_settings_path: str = "data/ai-settings.json"

    # Rate limiting (issue #163). Four independent budgets rather than one
    # global number, because a login attempt, an AI generation and an
    # outbound fetch cost the server wildly different amounts and share
    # nothing but a caller. Auth is keyed by IP (there is no account yet);
    # the other three are keyed by account. See
    # app.domain.services.rate_limiter for the enforcement and its
    # single-process caveat.
    rate_limit_auth_attempts: int = 10
    rate_limit_auth_window_seconds: int = 300
    rate_limit_ai_requests: int = 15
    rate_limit_ai_window_seconds: int = 60
    rate_limit_fetch_requests: int = 20
    rate_limit_fetch_window_seconds: int = 60
    rate_limit_upload_requests: int = 20
    rate_limit_upload_window_seconds: int = 60

    # Remote MCP over Streamable HTTP + OAuth (issue #196). Off by default —
    # every existing deployment (local stdio companion, desktop app,
    # self-hosted single-user install) keeps working with zero remote
    # surface at all until an operator opts in explicitly. Flipping this on
    # exposes the OAuth authorization/token endpoints and the
    # protected-resource/authorization-server metadata documents; it does
    # not by itself start a network listener (see apps/mcp's
    # `--transport=http`, which has its own, separate opt-in flag).
    remote_mcp_enabled: bool = False
    # Short-lived by design: a leaked access token is a bounded-time problem.
    mcp_access_token_ttl_minutes: int = 15
    # Rotated on every refresh (see MCPOAuthTokenModel.rotated_from_id); this
    # is only the outer bound after which a companion must re-run consent.
    mcp_refresh_token_ttl_days: int = 30
    # An authorization code is exchanged within one redirect round-trip in
    # every real client; two minutes is generous slack, not a target.
    mcp_authorization_code_ttl_seconds: int = 120
    # Used as the `issuer` in the authorization-server metadata document and
    # as the `resource` in the protected-resource one. Must match the origin
    # a remote client actually reaches this API on; the insecure default is
    # fine for local development only.
    mcp_issuer_url: str = "http://localhost:8000"
    # Where `authorization_endpoint` (in the authorization-server metadata
    # document) sends a connector's browser redirect. This backend has no
    # page-rendering layer of its own — GET/POST /api/v1/mcp/oauth/authorize
    # are a JSON API requiring a Bearer token, which a browser navigation
    # can never attach — so the endpoint a browser can actually be sent to
    # must be the frontend's consent page (OAuthAuthorizePage), which calls
    # that JSON API itself with the logged-in user's stored token. Must be
    # this deployment's real frontend origin plus "/oauth/authorize" (the
    # frontend route); the insecure localhost default is fine for local
    # development only, matching mcp_issuer_url's own default.
    mcp_consent_url: str = "http://localhost:5173/oauth/authorize"
    # `workspace` elsewhere in this codebase (MCPGrantModel, InvokeRequest,
    # is_valid_workspace) names an absolute local filesystem path the desktop
    # companion is sandboxed to — meaningless for a remote, browser-connected
    # OAuth client like Claude.ai, which has no local filesystem at all and
    # has no way to supply one (it sends RFC 8707's `resource`, not this
    # app-specific concept). This is the one workspace value remote grants
    # use instead, standing in for "no real workspace" — see
    # is_valid_workspace's special case for it. Must match the *deployed
    # remote MCP resource server's* LENSWORD_MCP_WORKSPACE exactly (like
    # mcp_issuer_url must match that service's LENSWORD_API_URL): that
    # service presents this same string on every tool-invocation request, and
    # a grant recorded under a different workspace would never match it.
    mcp_remote_workspace: str = "production"
    # Independent budget for the OAuth token endpoint (issue #196 TODO 4),
    # keyed by IP the same way rate_limit_login is — there is no account
    # bound to a code/refresh-token exchange attempt until it succeeds.
    rate_limit_mcp_oauth_attempts: int = 20
    rate_limit_mcp_oauth_window_seconds: int = 60

    @field_validator(
        "rate_limit_auth_attempts",
        "rate_limit_auth_window_seconds",
        "rate_limit_ai_requests",
        "rate_limit_ai_window_seconds",
        "rate_limit_fetch_requests",
        "rate_limit_fetch_window_seconds",
        "rate_limit_upload_requests",
        "rate_limit_upload_window_seconds",
        "rate_limit_mcp_oauth_attempts",
        "rate_limit_mcp_oauth_window_seconds",
        "mcp_access_token_ttl_minutes",
        "mcp_refresh_token_ttl_days",
        "mcp_authorization_code_ttl_seconds",
    )
    @classmethod
    def _positive_rate_limit(cls, value: int) -> int:
        """A non-positive limit or window either blocks every request or
        never resets, neither of which is a rate limit anyone chose on
        purpose. Fail at startup rather than at the first login."""
        if value <= 0:
            raise ValueError(f"must be greater than 0 (got {value})")
        return value

    @field_validator("database_url")
    @classmethod
    def _require_psycopg_driver(cls, value: str) -> str:
        """A bare `postgresql://`/`postgres://` URL — exactly what Supabase,
        Neon, Railway, and most managed Postgres providers hand you by
        default when you copy their connection string — makes SQLAlchemy
        default to the psycopg2 driver, which this project does not
        install (`requirements.txt` has psycopg[binary], psycopg3, not
        psycopg2). The failure mode is a `ModuleNotFoundError` deep inside
        Alembic's `env.py` on container startup, which gives no hint the
        actual problem is a missing `+psycopg` in the URL scheme —
        confirmed by hitting exactly this in a real deployment. Normalizing
        here means every future deployment of this app is immune to it,
        rather than every deployer needing to already know this gotcha."""
        if value.startswith("postgresql://"):
            return "postgresql+psycopg://" + value[len("postgresql://") :]
        if value.startswith("postgres://"):
            return "postgresql+psycopg://" + value[len("postgres://") :]
        return value

    @field_validator("scheduler_job_store")
    @classmethod
    def _known_job_store(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in SUPPORTED_JOB_STORES:
            raise ValueError(
                f"must be one of {', '.join(SUPPORTED_JOB_STORES)} (got '{value}')"
            )
        return normalized

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

    @field_validator("log_level")
    @classmethod
    def _known_log_level(cls, value: str) -> str:
        normalized = value.strip().upper()
        if normalized not in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
            raise ValueError(
                f"must be one of DEBUG, INFO, WARNING, ERROR, CRITICAL (got '{value}')"
            )
        return normalized

    @field_validator("ai_provider")
    @classmethod
    def _known_ai_provider(cls, value: str) -> str:
        """Reject a typo while the operator is still watching the console.

        Validating here rather than only in the factory means a misspelled
        AI_PROVIDER stops startup outright, instead of lying dormant until
        someone's first suggestion request turns it into a 500.

        A blank value is treated as "unset", not a typo: some deployment
        platforms (Render's dashboard included) create an env var key with
        an empty string rather than omitting it, and pydantic-settings only
        falls back to the field default when the variable is absent
        entirely — an empty string overrides "none" and previously crashed
        both app startup and every `alembic upgrade` with a ValidationError.
        """
        normalized = value.strip().lower()
        if normalized == "":
            return "none"
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
    "gemini_api_key",
    "gemini_model",
    "vertex_project_id",
    "vertex_location",
    "vertex_model",
    "openai_api_key",
    "openai_model",
)

# Secret fields among the above. A blank value submitted for one of these
# means "leave whatever is currently stored" rather than "clear it" — see
# save_effective_ai_settings's own comment for why: the GET side
# (AISettingsResponse in app/api/schemas/ai_settings.py) never echoes a
# configured secret back as `gemini_api_key_set`/`openai_api_key_set`
# booleans only, so there is nothing for an admin UI to resend on every
# save, and a literal blank must not be read as "clear this credential".
_AI_SECRET_FIELDS = ("gemini_api_key", "openai_api_key")

# Which Settings field(s) each cloud provider cannot run without, checked at
# admin-save time below so a broken combination (AI_PROVIDER=gemini with no
# key configured) fails the PUT with a clear 422 instead of surfacing as an
# unhandled error the next time something needs AI. This duplicates part of
# build_ai_provider's own check (app/infrastructure/ai_providers/factory.py)
# rather than importing it — the same deliberate duplication
# SUPPORTED_AI_PROVIDERS above already carries, and for the same reason:
# app/config.py cannot import from app/infrastructure/ without a circular
# import, since infrastructure/ai_providers/factory.py already imports
# `Settings` from here. Update both by hand when a provider's requirements
# change.
_CLOUD_PROVIDER_REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    "gemini": ("gemini_api_key",),
    "vertex": ("vertex_project_id",),
    "openai": ("openai_api_key",),
}


class AISettingsUpdate(BaseModel):
    ai_provider: str
    ollama_model: str
    ollama_base_url: str
    ai_max_output_tokens: int
    ai_context_max_chars: int
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-2.5-flash"
    vertex_project_id: str | None = None
    vertex_location: str = "us-central1"
    vertex_model: str = "gemini-2.5-flash"
    openai_api_key: str | None = None
    openai_model: str = "gpt-5.6-luna"


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
    """Validate and atomically persist the deployment-wide AI configuration.

    Based on the *currently effective* settings (get_effective_ai_settings),
    not just the environment defaults (get_settings) — that is what makes a
    blank incoming secret field mean "leave it alone" rather than "clear
    it": the previously persisted key is already present in `base`, and a
    blank in `values` for that same field is dropped before the merge below
    so it does not overwrite a real key with nothing.
    """
    base = get_effective_ai_settings()
    values = update.model_dump()
    if not values["ollama_model"].strip():
        raise ValueError("ollama_model must not be blank")
    if not values["ollama_base_url"].strip():
        raise ValueError("ollama_base_url must not be blank")
    for field in _AI_SECRET_FIELDS:
        if not (values.get(field) or "").strip():
            values[field] = getattr(base, field)
    provider = values["ai_provider"].strip().lower()
    for required_field in _CLOUD_PROVIDER_REQUIRED_FIELDS.get(provider, ()):
        if not (values.get(required_field) or "").strip():
            raise ValueError(f"AI_PROVIDER '{provider}' requires {required_field} to be set")
    validated = Settings(**(base.model_dump() | values))
    path = _runtime_override_path(base)
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as temporary:
        json.dump({field: getattr(validated, field) for field in _AI_OVERRIDE_FIELDS}, temporary)
        temporary.write("\n")
        temporary_path = Path(temporary.name)
    temporary_path.replace(path)
    return validated
