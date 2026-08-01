import os
from pathlib import Path
from collections.abc import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

settings = get_settings()

# Recycle below the 5-minute idle cutoff common to managed Postgres offerings
# and connection poolers, so the pool retires a connection before the far end
# does and a request never picks up one that was closed underneath it.
POOL_RECYCLE_SECONDS = 280


def engine_options(database_url: str, pool_size: int, max_overflow: int) -> tuple[dict, dict]:
    """Return `(connect_args, engine_kwargs)` for a database URL.

    A function rather than import-time branching so the dialect rules are
    testable without reimporting this module against patched settings — the
    engine below is built once, at import, and cannot be rebuilt afterwards.
    """
    if database_url.startswith("sqlite"):
        # SQLite alone needs check_same_thread relaxed: the scheduler delivers
        # reminders on worker threads that did not open the connection, which
        # SQLite otherwise refuses. The pool arguments are omitted rather than
        # set, because SQLite's default pool does not accept pool_size and
        # passing it raises instead of being ignored.
        return {"check_same_thread": False}, {}

    # Server-side connections are a bounded resource, unlike SQLite's file
    # handle, so the pool is sized explicitly rather than left at the default.
    # pre_ping costs one round trip per checkout and buys immunity to
    # connections killed underneath the pool — by an idle timeout, a failover,
    # or a restart — which otherwise surface as an unrelated request failing.
    return {}, {
        "pool_pre_ping": True,
        "pool_size": pool_size,
        "max_overflow": max_overflow,
        "pool_recycle": POOL_RECYCLE_SECONDS,
    }


_connect_args, _engine_kwargs = engine_options(
    settings.database_url, settings.db_pool_size, settings.db_max_overflow
)

if settings.database_url.startswith("sqlite:///./"):
    db_path = settings.database_url.replace("sqlite:///./", "")
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)

engine = create_engine(settings.database_url, connect_args=_connect_args, **_engine_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# Columns added to tables that already exist in deployed databases.
#
# create_all() creates missing *tables* but never missing *columns*, so a new
# column on an existing table is invisible to it and every query against that
# table then fails with "no such column". Until this project adopts a
# migration tool, additive columns are applied here.
#
# Each entry is (table, column, DDL type and default). Additive and idempotent
# only: no drops, no renames, no type changes. Anything beyond that needs a
# real migration story rather than another line in this tuple.
_ADDITIVE_COLUMNS: tuple[tuple[str, str, str], ...] = (
    # Issue #44. The default reproduces the previous naive-UTC behavior, so
    # accounts that existed before the column are unaffected until they
    # choose a zone.
    ("users", "time_zone", "VARCHAR(64) NOT NULL DEFAULT 'UTC'"),
)


def _apply_additive_columns() -> None:
    """Add columns missing from tables that already exist. Idempotent: it runs
    on every start and does nothing once the column is present."""
    existing_tables = set(inspect(engine).get_table_names())

    for table, column, ddl in _ADDITIVE_COLUMNS:
        # A table absent here does not exist yet, so create_all() below will
        # build it with the column already in place.
        if table not in existing_tables:
            continue
        # A fresh Inspector per entry, not one reused across the loop: an
        # Inspector caches the columns it has already read and would not see a
        # column that an earlier iteration added to the same table, so the
        # second entry touching a table would act on pre-ALTER metadata.
        if column in {c["name"] for c in inspect(engine).get_columns(table)}:
            continue
        with engine.begin() as conn:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))


def init_db() -> None:
    """Bring the configured database to the Alembic head revision.

    Schema creation no longer lives in application startup. Keeping that DDL
    path beside migrations would eventually let local development drift from
    the deployed schema, so both the Docker entrypoint and a direct Uvicorn
    launch use the same idempotent Alembic command.
    """
    from alembic import command
    from alembic.config import Config

    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    command.upgrade(config, "head")
