"""Add the semantic_relatedness_enabled opt-in flag (ADR 0006, issue #201).

Revision ID: 20260805_21
Revises: 20260805_20
"""
from alembic import op
import sqlalchemy as sa

revision = "20260805_21"
down_revision = "20260805_20"
branch_labels = None
depends_on = None


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "recall_settings" not in tables:
        return

    existing = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("recall_settings")}
    if "semantic_relatedness_enabled" not in existing:
        # NOT NULL with a default: every phase this flag gates is new, so an
        # existing account keeps today's behaviour (off) rather than becoming
        # null or silently opted in.
        op.add_column(
            "recall_settings",
            sa.Column(
                "semantic_relatedness_enabled", sa.Boolean(), nullable=False, server_default=sa.false()
            ),
        )


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "recall_settings" not in tables:
        return
    present = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("recall_settings")}
    with op.batch_alter_table("recall_settings") as batch:
        if "semantic_relatedness_enabled" in present:
            batch.drop_column("semantic_relatedness_enabled")
