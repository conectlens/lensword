"""Tests for Settings.database_url's driver-scheme normalization.

A bare `postgresql://`/`postgres://` URL — exactly what Supabase, Neon,
Railway, and most managed Postgres providers hand you by default — makes
SQLAlchemy default to the psycopg2 driver, which this project does not
install. Caught via a real ModuleNotFoundError in a real deployment; see
app/config.py's `_require_psycopg_driver` docstring.
"""
from __future__ import annotations

from app.config import Settings


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


def test_bare_postgresql_scheme_gets_the_psycopg_driver_added():
    settings = _settings(database_url="postgresql://user:pass@host:5432/db")
    assert settings.database_url == "postgresql+psycopg://user:pass@host:5432/db"


def test_bare_postgres_short_scheme_gets_the_psycopg_driver_added():
    settings = _settings(database_url="postgres://user:pass@host:5432/db")
    assert settings.database_url == "postgresql+psycopg://user:pass@host:5432/db"


def test_a_url_that_already_names_the_psycopg_driver_is_unchanged():
    settings = _settings(database_url="postgresql+psycopg://user:pass@host:5432/db")
    assert settings.database_url == "postgresql+psycopg://user:pass@host:5432/db"


def test_sqlite_url_passed_explicitly_is_unaffected():
    settings = _settings(database_url="sqlite:///./custom.db")
    assert settings.database_url == "sqlite:///./custom.db"
