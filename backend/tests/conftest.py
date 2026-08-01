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

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.api.deps import _ai_provider  # noqa: E402
from app.config import Settings, get_settings  # noqa: E402
from app.infrastructure.db import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _discard_the_throwaway_database():
    yield
    shutil.rmtree(_THROWAWAY_DB_DIR, ignore_errors=True)

AI_ENV_VARS = ("AI_PROVIDER", "OLLAMA_MODEL", "OLLAMA_BASE_URL")


@pytest.fixture(autouse=True)
def isolate_ai_settings(monkeypatch):
    """Make every test hermetic with respect to AI configuration.

    Two things would otherwise leak in. The README tells operators to put
    AI_PROVIDER=ollama in backend/.env, so a developer following the
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
    # Neutralise backend/.env as well: deleting environment variables does
    # not stop pydantic-settings reading the dotenv file.
    monkeypatch.setitem(Settings.model_config, "env_file", None)

    get_settings.cache_clear()
    _ai_provider.cache_clear()
    yield
    get_settings.cache_clear()
    _ai_provider.cache_clear()


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
