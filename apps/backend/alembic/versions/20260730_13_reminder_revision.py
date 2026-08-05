"""Server-authoritative revision on reminders, for cloud/local failover.

Revision ID: 20260730_13
Revises: 20260730_12
"""
from alembic import op
import sqlalchemy as sa

revision = "20260730_13"
down_revision = "20260730_12"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if "reminders" not in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    if "revision" not in _columns("reminders"):
        # Existing rows start at 1 rather than 0: a shell that has never synced
        # has nothing to compare against, and 1 reads as "first version".
        op.add_column(
            "reminders",
            sa.Column("revision", sa.Integer(), nullable=False, server_default=sa.text("1")),
        )


def downgrade() -> None:
    if "reminders" not in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    if "revision" in _columns("reminders"):
        with op.batch_alter_table("reminders") as batch:
            batch.drop_column("revision")
