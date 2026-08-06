"""Add bounded measurable companion activities (#194)."""

from alembic import op
import sqlalchemy as sa

revision = "20260806_31_companion"
down_revision = "20260807_32_merge_companion_heads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "companion_activities" in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    op.create_table(
        "companion_activities",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("session_id", sa.String(64), sa.ForeignKey("companion_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("activity_type", sa.String(32), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("expected_evaluation", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("response", sa.Text(), nullable=True),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("operation_id", sa.String(128), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.UniqueConstraint("session_id", "operation_id", name="uq_companion_activity_session_operation"),
    )
    op.create_index("ix_companion_activities_session_updated", "companion_activities", ["session_id", "updated_at"])


def downgrade() -> None:
    if "companion_activities" in set(sa.inspect(op.get_bind()).get_table_names()):
        op.drop_table("companion_activities")
