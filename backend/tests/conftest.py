import os
import shutil
import tempfile

# Point the application's own engine at a throwaway database before anything
# imports app.infrastructure.db, which builds its engine at import time from
# the settings. Entering the app's lifespan in a test calls init_db(), and
# init_db() writes through that module-level engine — no dependency override or
# monkeypatched SessionLocal can redirect it. Without this, running the test
# suite would create (or open, and migrate) the developer's real database.
_THROWAWAY_DB_DIR = tempfile.mkdtemp(prefix="lensword-tests-")
os.environ["DATABASE_URL"] = f"sqlite:///{_THROWAWAY_DB_DIR}/lensword-test.db"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.infrastructure.db import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _discard_the_throwaway_database():
    yield
    shutil.rmtree(_THROWAWAY_DB_DIR, ignore_errors=True)


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
