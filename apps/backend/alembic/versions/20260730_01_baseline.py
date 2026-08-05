"""Create the initial LensWord schema without destroying existing installs.

Revision ID: 20260730_01
Revises:
Create Date: 2026-07-30
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from app.infrastructure import models  # noqa: F401 - registers all metadata
from app.infrastructure.db import Base

revision = "20260730_01"
down_revision = None
branch_labels = None
depends_on = None

_STATE_TABLE = "alembic_baseline_state"


def _create_state(origin: str) -> None:
    op.create_table(
        _STATE_TABLE,
        sa.Column("origin", sa.String(length=16), nullable=False, primary_key=True),
    )
    op.bulk_insert(sa.table(_STATE_TABLE, sa.column("origin", sa.String())), [{"origin": origin}])


def upgrade() -> None:
    """Create a fresh schema or adopt a pre-Alembic LensWord database.

    LensWord used ``create_all()`` before this revision. Existing installations
    therefore already contain the application tables but have no Alembic
    version. We record that origin and leave those tables intact; a fresh
    database gets the metadata schema. The marker makes downgrade safe for
    both cases rather than treating an existing user's data as disposable.
    """
    connection = op.get_bind()
    existing = set(sa.inspect(connection).get_table_names())
    application_tables = set(Base.metadata.tables)

    if existing & application_tables:
        _create_state("legacy")
        return

    Base.metadata.create_all(bind=connection)
    _create_state("fresh")


def downgrade() -> None:
    connection = op.get_bind()
    if _STATE_TABLE not in set(sa.inspect(connection).get_table_names()):
        return

    origin = connection.execute(sa.text(f"SELECT origin FROM {_STATE_TABLE}")).scalar_one()
    if origin == "fresh":
        Base.metadata.drop_all(bind=connection)
    op.drop_table(_STATE_TABLE)
