"""Tests for the additive-column step in init_db (issue #44).

create_all() creates missing tables but never missing columns, so a column
added to a table that already exists in a deployed database is invisible to
it. Every query against that table would then fail with "no such column" —
the failure mode this step exists to prevent, and the one a fresh-database
test would never catch.
"""
from __future__ import annotations

import pathlib

import pytest
from sqlalchemy import create_engine, inspect, text

import app.infrastructure.db as db_module


@pytest.fixture()
def legacy_engine(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    """A database shaped like one that predates the time_zone column."""
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE users ("
                "  id INTEGER PRIMARY KEY,"
                "  username VARCHAR(64),"
                "  email VARCHAR(255),"
                "  hashed_password VARCHAR(255),"
                "  role VARCHAR(16),"
                "  created_at DATETIME,"
                "  is_active BOOLEAN,"
                "  streak_days INTEGER,"
                "  longest_streak_days INTEGER,"
                "  last_activity_date DATE,"
                "  total_words_learned INTEGER,"
                "  total_study_seconds INTEGER"
                ")"
            )
        )
        conn.execute(
            text(
                "INSERT INTO users (id, username, email, hashed_password, role,"
                " created_at, is_active, streak_days, longest_streak_days,"
                " total_words_learned, total_study_seconds)"
                " VALUES (1, 'existing', 'e@example.com', 'x', 'user',"
                " '2026-01-01 00:00:00', 1, 0, 0, 0, 0)"
            )
        )
    monkeypatch.setattr(db_module, "engine", engine)
    return engine


def _columns(engine) -> set[str]:
    return {c["name"] for c in inspect(engine).get_columns("users")}


def test_the_column_is_missing_before_the_step_runs(legacy_engine):
    """Guards the fixture itself: if this ever stops holding, the tests below
    would be passing against a database that never needed migrating."""
    assert "time_zone" not in _columns(legacy_engine)


def test_the_column_is_added_to_an_existing_table(legacy_engine):
    db_module._apply_additive_columns()

    assert "time_zone" in _columns(legacy_engine)


def test_rows_that_predate_the_column_default_to_utc(legacy_engine):
    """The default reproduces the previous behavior, so an existing account is
    not silently moved to a different zone."""
    db_module._apply_additive_columns()

    with legacy_engine.connect() as conn:
        stored = conn.execute(text("SELECT time_zone FROM users WHERE id = 1")).scalar_one()
    assert stored == "UTC"


def test_the_step_is_idempotent(legacy_engine):
    """It runs on every start, so a second pass must be a no-op rather than an
    error about a duplicate column."""
    db_module._apply_additive_columns()
    db_module._apply_additive_columns()

    assert "time_zone" in _columns(legacy_engine)


def test_existing_rows_survive_the_migration(legacy_engine):
    db_module._apply_additive_columns()

    with legacy_engine.connect() as conn:
        username = conn.execute(text("SELECT username FROM users WHERE id = 1")).scalar_one()
    assert username == "existing"


def test_two_columns_on_one_table_are_both_added(legacy_engine, monkeypatch):
    """Guards the loop against stale metadata.

    An Inspector caches the columns it has read, so one reused across the loop
    would not see a column added by an earlier iteration and would act on
    pre-ALTER metadata for the second entry on the same table.
    """
    monkeypatch.setattr(
        db_module,
        "_ADDITIVE_COLUMNS",
        (
            ("users", "time_zone", "VARCHAR(64) NOT NULL DEFAULT 'UTC'"),
            ("users", "locale", "VARCHAR(16) NOT NULL DEFAULT 'en'"),
        ),
    )

    db_module._apply_additive_columns()

    assert {"time_zone", "locale"} <= _columns(legacy_engine)


def test_a_database_with_no_tables_at_all_is_left_to_create_all(tmp_path, monkeypatch):
    """A fresh install has no users table yet; create_all builds it with the
    column already present, so the step must not try to ALTER it."""
    engine = create_engine(f"sqlite:///{tmp_path / 'fresh.db'}")
    monkeypatch.setattr(db_module, "engine", engine)

    db_module._apply_additive_columns()  # must not raise

    assert "users" not in inspect(engine).get_table_names()
