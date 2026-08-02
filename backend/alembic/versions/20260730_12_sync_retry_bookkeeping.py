"""Retry bookkeeping on sync operations, for observability and quarantine.

Revision ID: 20260730_12
Revises: 20260730_11
"""
from alembic import op
import sqlalchemy as sa

revision = "20260730_12"
down_revision = "20260730_11"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if "sync_operations" not in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    existing = _columns("sync_operations")
    if "attempts" not in existing:
        op.add_column(
            "sync_operations",
            sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        )
    if "error_class" not in existing:
        op.add_column("sync_operations", sa.Column("error_class", sa.String(32), nullable=True))


def downgrade() -> None:
    if "sync_operations" not in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    present = _columns("sync_operations")
    with op.batch_alter_table("sync_operations") as batch:
        for column in ("error_class", "attempts"):
            if column in present:
                batch.drop_column(column)
