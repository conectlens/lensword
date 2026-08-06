"""Add provider-neutral companion sessions and normalized turns (#193)."""

from alembic import op
import sqlalchemy as sa

revision = "20260806_30_companion"
down_revision = "20260806_29"
branch_labels = None
depends_on = None


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "companion_sessions" not in tables:
        op.create_table(
            "companion_sessions",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("connection_id", sa.String(128), nullable=False),
            sa.Column("client_id", sa.String(128), nullable=False),
            sa.Column("goal", sa.String(500), nullable=True),
            sa.Column("language", sa.String(64), nullable=True),
            sa.Column("group_id", sa.Integer(), sa.ForeignKey("groups.id"), nullable=True),
            sa.Column("difficulty", sa.String(32), nullable=True),
            sa.Column("active_activity", sa.String(128), nullable=True),
            sa.Column("consent_snapshot", sa.JSON(), nullable=False),
            sa.Column("summary", sa.Text(), nullable=True),
            sa.Column("status", sa.String(16), nullable=False),
            sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_companion_sessions_user_updated", "companion_sessions", ["user_id", "updated_at"])
        op.create_index("ix_companion_sessions_user_connection", "companion_sessions", ["user_id", "connection_id"])
    if "companion_turns" not in tables:
        op.create_table(
            "companion_turns",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("session_id", sa.String(64), sa.ForeignKey("companion_sessions.id", ondelete="CASCADE"), nullable=False),
            sa.Column("role", sa.String(16), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("activity_id", sa.String(128), nullable=True),
            sa.Column("operation_id", sa.String(128), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("session_id", "operation_id", name="uq_companion_turn_session_operation"),
        )
        op.create_index("ix_companion_turns_session_created", "companion_turns", ["session_id", "created_at"])


def downgrade() -> None:
    if "companion_turns" in set(sa.inspect(op.get_bind()).get_table_names()):
        op.drop_table("companion_turns")
    if "companion_sessions" in set(sa.inspect(op.get_bind()).get_table_names()):
        op.drop_table("companion_sessions")
