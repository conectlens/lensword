"""Offline mutation log and word revisions.

Revision ID: 20260730_11
Revises: 20260730_10
"""
from alembic import op
import sqlalchemy as sa

revision = "20260730_11"
down_revision = "20260730_10"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())

    if "sync_operations" not in tables:
        op.create_table(
            "sync_operations",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("operation_id", sa.String(64), nullable=False),
            sa.Column("entity_type", sa.String(32), nullable=False),
            sa.Column("entity_id", sa.Integer(), nullable=True),
            sa.Column("operation", sa.String(16), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("base_revision", sa.Integer(), nullable=True),
            sa.Column("status", sa.String(16), nullable=False),
            sa.Column("conflict_reason", sa.Text(), nullable=True),
            sa.Column("server_sequence", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            # The idempotency mechanism itself: a client retrying after a lost
            # response inserts this same row and loses to itself.
            sa.UniqueConstraint("user_id", "operation_id", name="uq_sync_user_operation"),
        )
        op.create_index("ix_sync_operations_user_id", "sync_operations", ["user_id"])
        op.create_index("ix_sync_operations_status", "sync_operations", ["status"])
        op.create_index("ix_sync_operations_created_at", "sync_operations", ["created_at"])
        # Pulling changes is "everything for this account above my cursor", so
        # the pair is the index that query actually needs.
        op.create_index(
            "ix_sync_operations_user_sequence", "sync_operations", ["user_id", "server_sequence"]
        )

    if "words" in tables and "revision" not in _columns("words"):
        # Existing rows start at revision 1 rather than 0: a client that has
        # never synced has no base revision to compare against anyway, and 1
        # reads as "first version" rather than "unset".
        op.add_column(
            "words",
            sa.Column("revision", sa.Integer(), nullable=False, server_default=sa.text("1")),
        )


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "words" in tables and "revision" in _columns("words"):
        with op.batch_alter_table("words") as batch:
            batch.drop_column("revision")
    if "sync_operations" in tables:
        op.drop_table("sync_operations")
