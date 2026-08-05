"""The baseline migration must work for both new and pre-Alembic databases."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect

from app.infrastructure import models  # noqa: F401 - registers metadata
from app.infrastructure.db import Base

BACKEND_DIR = Path(__file__).resolve().parents[1]


def _alembic(database_url: str, *args: str) -> None:
    env = os.environ | {"DATABASE_URL": database_url}
    subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", *args],
        cwd=BACKEND_DIR,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )


def test_baseline_upgrade_and_downgrade_create_and_remove_a_fresh_schema(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'fresh.db'}"

    _alembic(database_url, "upgrade", "head")
    upgraded = inspect(create_engine(database_url)).get_table_names()
    assert {"users", "words", "review_sessions", "alembic_version"} <= set(upgraded)

    _alembic(database_url, "downgrade", "base")
    downgraded = inspect(create_engine(database_url)).get_table_names()
    assert "users" not in downgraded
    assert "alembic_baseline_state" not in downgraded


def test_baseline_adopts_and_preserves_an_existing_sqlite_schema(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'existing.db'}"
    engine = create_engine(database_url)
    Base.metadata.create_all(bind=engine)

    _alembic(database_url, "upgrade", "head")
    _alembic(database_url, "downgrade", "base")

    tables = set(inspect(create_engine(database_url)).get_table_names())
    assert {"users", "words", "review_sessions"} <= tables
    assert "alembic_baseline_state" not in tables
