"""Persist AI enrichment fields on vocabulary words.

Revision ID: 20260730_02
Revises: 20260730_01
Create Date: 2026-07-30
"""
from alembic import op
import sqlalchemy as sa

revision = "20260730_02"
down_revision = "20260730_01"
branch_labels = None
depends_on = None


_COLUMNS = (
    ("definition", sa.Text()),
    ("part_of_speech", sa.String(length=64)),
    ("cefr_level", sa.String(length=8)),
    ("pronunciation", sa.String(length=255)),
    ("collocations", sa.JSON()),
    ("tags", sa.JSON()),
    ("ai_confidence", sa.Float()),
    ("ai_provider", sa.String(length=64)),
    ("ai_model", sa.String(length=255)),
)


def upgrade() -> None:
    existing = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("words")}
    for name, column_type in _COLUMNS:
        # The Phase-0 baseline creates ``Base.metadata`` for brand-new
        # installs. Its metadata already includes these fields when this
        # revision is added later, whereas adopted legacy databases need the
        # ALTERs. Supporting both preserves the baseline's fresh/legacy
        # contract without a destructive rebuild.
        if name not in existing:
            op.add_column("words", sa.Column(name, column_type, nullable=True))


def downgrade() -> None:
    # batch mode keeps the downgrade working for the SQLite development DB.
    with op.batch_alter_table("words") as batch:
        for name, _ in reversed(_COLUMNS):
            batch.drop_column(name)
