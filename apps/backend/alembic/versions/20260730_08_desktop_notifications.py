"""Outbox table for desktop notifications awaiting collection by a shell.

Revision ID: 20260730_08
Revises: 20260730_07
"""
from alembic import op
import sqlalchemy as sa

revision = "20260730_08"
down_revision = "20260730_07"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "desktop_notifications" not in set(sa.inspect(op.get_bind()).get_table_names()):
        op.create_table(
            "desktop_notifications",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("message", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            # Null means "not yet collected by a shell". The pending query
            # selects on it, so it is part of the composite index below rather
            # than only a payload column.
            sa.Column("delivered_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_desktop_notifications_user_id", "desktop_notifications", ["user_id"])
        op.create_index("ix_desktop_notifications_created_at", "desktop_notifications", ["created_at"])
        op.create_index(
            "ix_desktop_notifications_user_undelivered",
            "desktop_notifications",
            ["user_id", "delivered_at"],
        )


def downgrade() -> None:
    if "desktop_notifications" in set(sa.inspect(op.get_bind()).get_table_names()):
        op.drop_table("desktop_notifications")
