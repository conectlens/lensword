"""Add durable companion loop budgets and sampling provenance (#195)."""

from alembic import op
import sqlalchemy as sa

revision = "20260807_38_companion_loop"
down_revision = "20260807_38_mcp_oauth"
branch_labels = None
depends_on = None


def upgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())

    if "companion_loop_states" not in existing:
        op.create_table(
            "companion_loop_states",
            sa.Column("session_id", sa.String(64), sa.ForeignKey("companion_sessions.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("budget_tool_calls", sa.Integer(), nullable=False),
            sa.Column("budget_samples", sa.Integer(), nullable=False),
            sa.Column("budget_elapsed_seconds", sa.Float(), nullable=False),
            sa.Column("budget_generated_tokens", sa.Integer(), nullable=False),
            sa.Column("budget_activities", sa.Integer(), nullable=False),
            sa.Column("budget_writes", sa.Integer(), nullable=False),
            sa.Column("tool_calls", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("samples", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("generated_tokens", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("activities", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("writes", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("stopped_reason", sa.String(32), nullable=True),
            sa.Column("started_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        )
        op.create_index("ix_companion_loop_states_user_id", "companion_loop_states", ["user_id"])

    if "companion_sampling_events" not in existing:
        op.create_table(
            "companion_sampling_events",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("session_id", sa.String(64), sa.ForeignKey("companion_sessions.id", ondelete="CASCADE"), nullable=False),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("requester", sa.String(255), nullable=False),
            sa.Column("host_client_id", sa.String(128), nullable=True),
            sa.Column("model", sa.String(128), nullable=True),
            sa.Column("prompt_template_version", sa.String(32), nullable=False),
            sa.Column("source_facts_ref", sa.String(128), nullable=False),
            sa.Column("validation_result", sa.String(255), nullable=False),
            sa.Column("fallback_path", sa.String(64), nullable=False),
            sa.Column("previous_hash", sa.String(64), nullable=False),
            sa.Column("event_hash", sa.String(64), nullable=False, unique=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_companion_sampling_events_session_id", "companion_sampling_events", ["session_id"])
        op.create_index("ix_companion_sampling_events_user_id", "companion_sampling_events", ["user_id"])
        op.create_index("ix_companion_sampling_events_requester", "companion_sampling_events", ["requester"])
        op.create_index(
            "ix_companion_sampling_events_session_created",
            "companion_sampling_events",
            ["session_id", "created_at"],
        )


def downgrade() -> None:
    op.drop_index("ix_companion_sampling_events_session_created", table_name="companion_sampling_events")
    op.drop_index("ix_companion_sampling_events_requester", table_name="companion_sampling_events")
    op.drop_index("ix_companion_sampling_events_user_id", table_name="companion_sampling_events")
    op.drop_index("ix_companion_sampling_events_session_id", table_name="companion_sampling_events")
    op.drop_table("companion_sampling_events")

    op.drop_index("ix_companion_loop_states_user_id", table_name="companion_loop_states")
    op.drop_table("companion_loop_states")
