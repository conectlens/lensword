import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import _ai_provider
from app.config import Settings, get_settings
from app.infrastructure.db import Base, get_db
from app.main import app

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


@pytest.fixture()
def db_session():
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
