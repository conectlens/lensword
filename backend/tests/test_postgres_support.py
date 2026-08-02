"""Dialect portability: the engine setup and the settings that drive it.

The rest of the suite is dialect-agnostic and is run twice in CI — once on
SQLite, once on Postgres. These tests cover the parts that are *about* the
dialect, which running the suite on either one alone would not exercise.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.infrastructure.db import POOL_RECYCLE_SECONDS, engine_options

POSTGRES_URL = "postgresql+psycopg://lensword:lensword@localhost:5432/lensword"


def test_sqlite_relaxes_check_same_thread():
    """The scheduler delivers reminders on worker threads that did not open the
    connection, which SQLite refuses by default."""
    connect_args, _ = engine_options("sqlite:///./data/lensword.db", 5, 10)

    assert connect_args == {"check_same_thread": False}


def test_sqlite_is_given_no_pool_arguments():
    """Not merely unnecessary — SQLite's default pool rejects `pool_size`, so
    passing it raises at startup rather than being ignored."""
    _, engine_kwargs = engine_options("sqlite:///./data/lensword.db", 5, 10)

    assert engine_kwargs == {}


def test_postgres_is_not_given_check_same_thread():
    """psycopg has no such parameter; it would be a connect-time error rather
    than a no-op."""
    connect_args, _ = engine_options(POSTGRES_URL, 5, 10)

    assert connect_args == {}


def test_postgres_pool_is_bounded_and_pre_pinged():
    _, engine_kwargs = engine_options(POSTGRES_URL, 7, 3)

    assert engine_kwargs["pool_size"] == 7
    assert engine_kwargs["max_overflow"] == 3
    # Without pre_ping, a connection closed by an idle timeout or a failover is
    # handed to a request and fails there instead of being replaced.
    assert engine_kwargs["pool_pre_ping"] is True


def test_connections_are_recycled_before_a_five_minute_idle_cutoff():
    """Managed Postgres offerings and poolers commonly drop idle connections at
    five minutes. Recycling after that is indistinguishable from not recycling
    at all."""
    assert POOL_RECYCLE_SECONDS < 300


@pytest.mark.parametrize("url", ["sqlite:///:memory:", "sqlite:////tmp/x.db"])
def test_every_sqlite_url_form_is_recognised(url):
    connect_args, engine_kwargs = engine_options(url, 5, 10)

    assert connect_args == {"check_same_thread": False}
    assert engine_kwargs == {}


@pytest.mark.parametrize("field", ["db_pool_size", "db_max_overflow"])
def test_a_negative_pool_bound_is_rejected_at_startup(field):
    """SQLAlchemy reads a negative bound as 'unbounded', which against a shared
    connection cap is the opposite of what setting it is for."""
    with pytest.raises(ValidationError):
        Settings(**{field: -1}, _env_file=None)


@pytest.mark.parametrize("field", ["db_pool_size", "db_max_overflow"])
def test_zero_is_allowed(field):
    """0 overflow is a legitimate hard cap, and 0 pool size is meaningful for
    pool classes that do not keep connections."""
    assert getattr(Settings(**{field: 0}, _env_file=None), field) == 0


def test_the_default_url_needs_no_database_server():
    """A fresh checkout must run without installing Postgres first.

    Read off the field rather than an instance: an instance picks up
    DATABASE_URL from the environment, which conftest sets — so instantiating
    here would assert whatever dialect the suite happens to be running against
    rather than the shipped default.
    """
    assert Settings.model_fields["database_url"].default.startswith("sqlite")
