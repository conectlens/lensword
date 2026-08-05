"""Migration 20260805_20 backfills FSRS stability for reviewed words on
accounts using FSRS, and leaves SM-2 accounts and never-reviewed words alone
(issue #173 TODO 0)."""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import Boolean, DateTime, Float, Integer, String, create_engine, inspect, text

BACKEND_DIR = Path(__file__).resolve().parents[1]
_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc).replace(tzinfo=None)


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


def _dummy_value(column: dict):
    if column["default"] is not None or column["nullable"]:
        return None
    col_type = column["type"]
    if isinstance(col_type, Boolean):
        return False
    if isinstance(col_type, Integer):
        return 0
    if isinstance(col_type, Float):
        return 0.0
    if isinstance(col_type, DateTime):
        return _NOW
    if isinstance(col_type, String):
        return "x"
    return "x"


def _insert(engine, table: str, **overrides) -> None:
    columns = inspect(engine).get_columns(table)
    values = {}
    for c in columns:
        if c["name"] == "id" and c.get("autoincrement", True):
            continue
        values[c["name"]] = _dummy_value(c)
    values.update(overrides)
    values = {k: v for k, v in values.items() if v is not None or k in overrides}

    names = ", ".join(values)
    placeholders = ", ".join(f":{k}" for k in values)
    with engine.begin() as conn:
        conn.execute(text(f"INSERT INTO {table} ({names}) VALUES ({placeholders})"), values)


def test_backfill_only_touches_reviewed_words_on_fsrs_accounts(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'legacy.db'}"

    # The baseline migration (20260730_01) builds its schema from the live
    # ORM metadata, so `stability` already exists here nullable and unset —
    # equivalent, for backfill purposes, to a pre-fix row that predates the
    # column. What this test actually exercises is 20260805_20's backfill
    # UPDATE, which runs unconditionally regardless of whether the add_column
    # step above it had anything to do.
    _alembic(database_url, "upgrade", "20260730_19")
    engine = create_engine(database_url)

    # user 1: explicit fsrs row, one reviewed word (the bug's fixed point).
    _insert(engine, "users", id=1, username="fsrs_user", email="f@x.com", created_at=_NOW)
    _insert(engine, "recall_settings", user_id=1, scheduler="fsrs")
    _insert(engine, "groups", id=1, owner_id=1, name="g1", target_language="es", created_at=_NOW)
    _insert(engine, "words", id=1, group_id=1, term="hola", target_language="es", interval_days=1.0, due_at=_NOW)

    # user 2: explicit sm2 row (migration 14's pin) — must stay untouched.
    _insert(engine, "users", id=2, username="sm2_user", email="s@x.com", created_at=_NOW)
    _insert(engine, "recall_settings", user_id=2, scheduler="sm2")
    _insert(engine, "groups", id=2, owner_id=2, name="g2", target_language="es", created_at=_NOW)
    _insert(engine, "words", id=2, group_id=2, term="adios", target_language="es", interval_days=1.0, due_at=_NOW)

    # user 3: no recall_settings row at all — entity default is fsrs.
    _insert(engine, "users", id=3, username="default_user", email="d@x.com", created_at=_NOW)
    _insert(engine, "groups", id=3, owner_id=3, name="g3", target_language="es", created_at=_NOW)
    _insert(engine, "words", id=3, group_id=3, term="gracias", target_language="es", interval_days=1.0, due_at=_NOW)

    # user 1 also has a never-reviewed word — nothing to backfill.
    _insert(engine, "words", id=4, group_id=1, term="por favor", target_language="es", interval_days=0, due_at=_NOW)

    _alembic(database_url, "upgrade", "head")
    engine = create_engine(database_url)

    with engine.connect() as conn:
        stability = dict(conn.execute(text("SELECT id, stability FROM words")).fetchall())

    from math import log

    expected = round(max(1.0, 1.0 / -log(0.9)), 10)
    assert round(stability[1], 10) == expected  # explicit fsrs, reviewed
    assert stability[2] is None  # explicit sm2, untouched
    assert round(stability[3], 10) == expected  # no row -> default fsrs, reviewed
    assert stability[4] is None  # never reviewed, nothing to backfill


def test_downgrade_removes_the_column(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'roundtrip.db'}"

    _alembic(database_url, "upgrade", "head")
    _alembic(database_url, "downgrade", "20260730_19")

    engine = create_engine(database_url)
    assert "stability" not in {c["name"] for c in inspect(engine).get_columns("words")}
