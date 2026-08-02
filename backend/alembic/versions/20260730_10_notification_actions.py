"""Actionable notifications: payload provenance, expiry, and the action taken.

Revision ID: 20260730_10
Revises: 20260730_09
"""
from alembic import op
import sqlalchemy as sa

revision = "20260730_10"
down_revision = "20260730_09"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())

    if "desktop_notifications" in tables:
        existing = _columns("desktop_notifications")
        # Added one at a time and guarded, because this runs against databases
        # that already hold rows from 20260730_08.
        if "reminder_id" not in existing:
            op.add_column(
                "desktop_notifications",
                sa.Column("reminder_id", sa.Integer(), sa.ForeignKey("reminders.id"), nullable=True),
            )
        if "expires_at" not in existing:
            op.add_column("desktop_notifications", sa.Column("expires_at", sa.DateTime(), nullable=True))
        if "action" not in existing:
            op.add_column("desktop_notifications", sa.Column("action", sa.String(32), nullable=True))
        if "action_at" not in existing:
            op.add_column("desktop_notifications", sa.Column("action_at", sa.DateTime(), nullable=True))

    if "recall_settings" in tables:
        existing = _columns("recall_settings")
        # NOT NULL with a default: existing accounts keep today's behaviour
        # (details shown, notifications not paused) rather than becoming null.
        if "hide_notification_details" not in existing:
            op.add_column(
                "recall_settings",
                sa.Column(
                    "hide_notification_details",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.false(),
                ),
            )
        if "notifications_paused" not in existing:
            op.add_column(
                "recall_settings",
                sa.Column(
                    "notifications_paused", sa.Boolean(), nullable=False, server_default=sa.false()
                ),
            )


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    # Batch mode, because SQLite refuses to DROP a column named in a foreign
    # key ("unknown column reminder_id in foreign key definition") — it can
    # only rebuild the table. On Postgres batch mode issues ordinary ALTERs, so
    # one code path serves both.
    if "desktop_notifications" in tables:
        present = _columns("desktop_notifications")
        with op.batch_alter_table("desktop_notifications") as batch:
            for column in ("action_at", "action", "expires_at", "reminder_id"):
                if column in present:
                    batch.drop_column(column)
    if "recall_settings" in tables:
        present = _columns("recall_settings")
        with op.batch_alter_table("recall_settings") as batch:
            for column in ("notifications_paused", "hide_notification_details"):
                if column in present:
                    batch.drop_column(column)
