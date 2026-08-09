import os
import shutil
import tempfile

# Point the application's own engine at a throwaway database before anything
# imports app.infrastructure.db, which builds its engine at import time from
# the settings. Entering the app's lifespan in a test calls init_db(), and
# init_db() writes through that module-level engine — no dependency override or
# monkeypatched SessionLocal can redirect it. Without this, running the test
# suite would create (or open, and migrate) the developer's real database.
#
# Every app.* import below must stay after this assignment for that reason,
# which is why they all carry a noqa: E402.
#
# TEST_DATABASE_URL runs the whole suite against Postgres instead (ROADMAP 4.0).
# CI sets it in a second job so both dialects are covered; unset, the suite
# still needs no database server. It must name a database the run may drop and
# recreate — see the `db_session` fixture.
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
_USING_POSTGRES = bool(TEST_DATABASE_URL) and not TEST_DATABASE_URL.startswith("sqlite")

_THROWAWAY_DB_DIR = tempfile.mkdtemp(prefix="lensword-tests-")
os.environ["DATABASE_URL"] = TEST_DATABASE_URL or f"sqlite:///{_THROWAWAY_DB_DIR}/lensword-test.db"

# The suite runs one process and asserts on delivery, not on concurrency, so
# jobs stay in memory. A database job store would also have APScheduler create
# and share its own table across tests, which is state the fixtures do not own
# and cannot reset.
os.environ["SCHEDULER_JOB_STORE"] = "memory"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.api.deps import _ai_provider, get_rate_limiter  # noqa: E402
from app.config import Settings, get_settings  # noqa: E402
from app.infrastructure.db import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _discard_the_throwaway_database():
    yield
    shutil.rmtree(_THROWAWAY_DB_DIR, ignore_errors=True)

AI_ENV_VARS = (
    "AI_PROVIDER",
    "OLLAMA_MODEL",
    "OLLAMA_BASE_URL",
    # Issue #315's cloud providers: a developer's own exported
    # GEMINI_API_KEY/OPENAI_API_KEY (or a checked-out apps/backend/.env
    # setting one) must not leak into the suite any more than
    # OLLAMA_BASE_URL already could not — see this fixture's own docstring.
    "GEMINI_API_KEY",
    "GEMINI_MODEL",
    "VERTEX_PROJECT_ID",
    "VERTEX_LOCATION",
    "VERTEX_MODEL",
    "OPENAI_API_KEY",
    "OPENAI_MODEL",
    # Bring-Your-Own-Key AI credentials: a developer's own exported
    # AI_CREDENTIAL_ENCRYPTION_KEY must not leak into the suite either —
    # same reasoning as every other AI_* var above.
    "AI_CREDENTIAL_ENCRYPTION_KEY",
)


@pytest.fixture(autouse=True)
def isolate_ai_settings(monkeypatch):
    """Make every test hermetic with respect to AI configuration.

    Two things would otherwise leak in. The README tells operators to put
    AI_PROVIDER=ollama in apps/backend/.env, so a developer following the
    documentation would turn the suite red and — worse — have it place real
    HTTP calls against their running daemon. And because both the settings
    and the built provider are process-wide lru_caches, the first test that
    does enable AI would poison every test after it.

    Clearing on the way in and out is deliberate: a test that deliberately
    enables AI (see test_ai_provider_config.py) must not affect its
    neighbours in either direction.
    """
    for name in AI_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv(name.lower(), raising=False)
    # Neutralise apps/backend/.env as well: deleting environment variables does
    # not stop pydantic-settings reading the dotenv file.
    monkeypatch.setitem(Settings.model_config, "env_file", None)

    get_settings.cache_clear()
    _ai_provider.cache_clear()
    yield
    get_settings.cache_clear()
    _ai_provider.cache_clear()


@pytest.fixture(autouse=True)
def isolate_rate_limits():
    """Every test starts with an empty rate limiter.

    The limiter is a process-wide singleton (app.api.deps._rate_limiter), same
    as _ai_provider above — without a reset here, a test earlier in the run
    that logs in or calls an AI endpoint several times would count toward the
    budget of every test after it, and an unrelated test could start failing
    only when run after a specific neighbour.
    """
    get_rate_limiter().reset()
    yield
    get_rate_limiter().reset()


@pytest.fixture(autouse=True)
def isolate_coach_cache():
    """Every test starts with an empty companion-coach content cache
    (#187 TODO 5).

    `app.api.routers.interventions._coach_cache` is a process-wide
    singleton, the same shape as `_ai_provider`/the rate limiter above. Each
    test's database is fresh (see `db_session`), so ids restart from 1 every
    time — without a reset here, two unrelated tests that happen to build
    the same (user_id=1, plan_id=1, ...) cache key would see each other's
    cached content instead of exercising their own scenario.
    """
    from app.api.routers.interventions import _coach_cache

    _coach_cache.clear()
    yield
    _coach_cache.clear()


@pytest.fixture(autouse=True)
def isolate_language_profile_cache():
    """Every test starts with an empty language-profile cache (issue #342).

    Exactly the hazard `isolate_coach_cache` above describes, and for exactly
    the same reason: `LANGUAGE_PROFILE_CACHE` is a process-wide singleton
    keyed by user id, and each test's database restarts ids from 1. Without a
    reset, a test that adds words for user 1 could read the profile another
    test had already cached for its own user 1.
    """
    from app.application.use_cases.mcp_dev_workflow import LANGUAGE_PROFILE_CACHE

    LANGUAGE_PROFILE_CACHE.clear()
    yield
    LANGUAGE_PROFILE_CACHE.clear()


@pytest.fixture(scope="session")
def _postgres_engine():
    """One engine and one schema build for the whole Postgres run.

    Creating and dropping twenty-odd tables per test is affordable against an
    in-memory SQLite file and is not against a real server, so the schema is
    built once here and each test is isolated by a transaction instead.
    """
    if not _USING_POSTGRES:
        yield None
        return

    engine = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    # Dropped first so a previous interrupted run cannot leave a stale column
    # behind and turn a schema mismatch into a confusing test failure.
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture()
def db_session(_postgres_engine):
    if _postgres_engine is None:
        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=engine)
        TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        session = TestingSessionLocal()
        try:
            yield session
        finally:
            session.close()
            engine.dispose()
        return

    # Postgres: every test runs inside a transaction that is rolled back, so
    # tests do not see each other's rows despite sharing one database.
    #
    # `join_transaction_mode="create_savepoint"` is what makes this work with
    # code that commits — the notification adapter and several use cases do.
    # Without it a commit inside the test would end the outer transaction and
    # the rollback below would have nothing left to undo, leaking rows into
    # every subsequent test.
    connection = _postgres_engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture()
def client(db_session):
    def _override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture()
def auth_headers(client):
    def _register(username="alex", email="alex@example.com", password="supersecret1"):
        resp = client.post(
            "/api/v1/auth/register", json={"username": username, "email": email, "password": password}
        )
        assert resp.status_code == 201, resp.text
        token = resp.json()["token"]["access_token"]
        return {"Authorization": f"Bearer {token}"}

    return _register
