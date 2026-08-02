"""Role-play scenario attempts (issue #136).

Revision ID: 20260730_19
Revises: 20260730_18

An attempt wraps a conversation rather than replacing it, so the transport,
corrections and history from #135 are reused. `session_id` is unique: one
conversation belongs to at most one attempt, and two attempts sharing a
conversation would make "how did this attempt go" unanswerable.

`scenario_key` is text rather than a foreign key because the catalog is a code
constant with no row to point at — and storing the key as text means an attempt
survives a scenario being renamed or retired.

`evaluation` stays null when an attempt was too short to judge. That is
deliberately different from a zero score, which would be a claim the learner
did badly rather than an admission we cannot tell.
"""
from alembic import op
import sqlalchemy as sa

revision = "20260730_19"
down_revision = "20260730_18"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "scenario_attempts" in set(sa.inspect(bind).get_table_names()):
        return

    op.create_table(
        "scenario_attempts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "session_id",
            sa.Integer(),
            sa.ForeignKey("conversation_sessions.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("scenario_key", sa.String(length=64), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("evaluation", sa.JSON(), nullable=True),
    )
    op.create_index("ix_scenario_attempts_user_id", "scenario_attempts", ["user_id"])
    op.create_index("ix_scenario_attempts_scenario_key", "scenario_attempts", ["scenario_key"])
    op.create_index("ix_scenario_attempts_started_at", "scenario_attempts", ["started_at"])


def downgrade() -> None:
    bind = op.get_bind()
    if "scenario_attempts" in set(sa.inspect(bind).get_table_names()):
        op.drop_table("scenario_attempts")
