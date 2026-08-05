"""Persist the selected review scheduling algorithm.

Revision ID: 20260730_03
Revises: 20260730_02
Create Date: 2026-07-30
"""

from alembic import op
import sqlalchemy as sa

revision = "20260730_03"
down_revision = "20260730_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    existing = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("recall_settings")}
    if "scheduler" not in existing:
        op.add_column(
            "recall_settings",
            sa.Column("scheduler", sa.String(length=16), nullable=False, server_default="sm2"),
        )


def downgrade() -> None:
    with op.batch_alter_table("recall_settings") as batch:
        batch.drop_column("scheduler")
