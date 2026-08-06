"""Add durable capability-negotiated companion tasks (#197)."""

from alembic import op
import sqlalchemy as sa

revision = "20260807_33_companion_tasks"
down_revision = "20260806_31_companion"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Test/dev databases can contain a table created by an interrupted first
    # startup. Treat the migration as idempotent, like the companion activity
    # migration, so a later startup can stamp the revision instead of failing
    # before the API is available.
    if "companion_tasks" in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    op.create_table(
        "companion_tasks",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("session_id", sa.String(64), sa.ForeignKey("companion_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("task_type", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("total_units", sa.Integer(), nullable=False),
        sa.Column("completed_units", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("error", sa.String(500), nullable=True),
        sa.Column("operation_id", sa.String(128), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.UniqueConstraint("session_id", "operation_id", name="uq_companion_task_session_operation"),
    )
    op.create_index("ix_companion_tasks_session_id", "companion_tasks", ["session_id"])
    op.create_index("ix_companion_tasks_user_id", "companion_tasks", ["user_id"])
    op.create_index("ix_companion_tasks_status", "companion_tasks", ["status"])
    op.create_index("ix_companion_tasks_expires_at", "companion_tasks", ["expires_at"])
    op.create_index("ix_companion_tasks_session_updated", "companion_tasks", ["session_id", "updated_at"])
    op.create_index("ix_companion_tasks_expiry_status", "companion_tasks", ["expires_at", "status"])


def downgrade() -> None:
    op.drop_index("ix_companion_tasks_expiry_status", table_name="companion_tasks")
    op.drop_index("ix_companion_tasks_session_updated", table_name="companion_tasks")
    op.drop_index("ix_companion_tasks_expires_at", table_name="companion_tasks")
    op.drop_index("ix_companion_tasks_status", table_name="companion_tasks")
    op.drop_index("ix_companion_tasks_user_id", table_name="companion_tasks")
    op.drop_index("ix_companion_tasks_session_id", table_name="companion_tasks")
    op.drop_table("companion_tasks")
