import os
from collections.abc import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

settings = get_settings()

_connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}

if settings.database_url.startswith("sqlite:///./"):
    db_path = settings.database_url.replace("sqlite:///./", "")
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)

engine = create_engine(settings.database_url, connect_args=_connect_args)
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
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    for table, column, ddl in _ADDITIVE_COLUMNS:
        # A table absent here does not exist yet, so create_all() below will
        # build it with the column already in place.
        if table not in existing_tables:
            continue
        if column in {c["name"] for c in inspector.get_columns(table)}:
            continue
        with engine.begin() as conn:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))


def init_db() -> None:
    # Import models so they're registered on Base.metadata before create_all.
    from app.infrastructure import models  # noqa: F401

    _apply_additive_columns()
    Base.metadata.create_all(bind=engine)
