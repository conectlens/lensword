"""Persist learning observations (AI Learning Diagnosis epic, issue #182).

Revision ID: 20260806_23
Revises: 20260805_22

Phase 0 (#181) defined the LearningObservation contract with nothing to
store it in — the table did not exist, and review submission never wrote
one regardless of the settings flag. This is that table.

Append-only, the same reasoning as mistake_events (20260730_15): a wrong
observation is corrected by a later, separate row, never rewritten.

The unique constraint on (user_id, operation_id) makes submission
idempotent, the same pattern sync_operations (20260730_11) already uses:
a client that retries after a lost response inserts the same row and loses
the race with itself rather than being recorded twice.
"""
from alembic import op
import sqlalchemy as sa

revision = "20260806_23"
down_revision = "20260805_22"
branch_labels = None
depends_on = None

_TABLE = "learning_observations"


def upgrade() -> None:
    bind = op.get_bind()
    if _TABLE in set(sa.inspect(bind).get_table_names()):
        return

    op.create_table(
        _TABLE,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("observation_id", sa.String(length=64), nullable=False, unique=True),
        sa.Column("operation_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("word_id", sa.Integer(), sa.ForeignKey("words.id"), nullable=False),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("session_mode", sa.String(length=16), nullable=False),
        sa.Column("observed_at", sa.DateTime(), nullable=False),
        sa.Column("attempted_answer", sa.String(length=255), nullable=True),
        sa.Column("response_time_ms", sa.Integer(), nullable=True),
        sa.Column("prompt_direction", sa.String(length=32), nullable=True),
        sa.Column("hint_used", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("answer_format", sa.String(length=32), nullable=True),
        sa.Column("modality", sa.String(length=32), nullable=True),
        sa.Column("intervention_plan_ref", sa.String(length=64), nullable=True),
        sa.Column("self_reported_confidence", sa.Float(), nullable=True),
        sa.Column("context_source", sa.String(length=64), nullable=True),
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_unique_constraint(
        "uq_learning_observation_user_operation", _TABLE, ["user_id", "operation_id"]
    )
    op.create_index("ix_learning_observations_observation_id", _TABLE, ["observation_id"])
    op.create_index("ix_learning_observations_user_word", _TABLE, ["user_id", "word_id"])
    op.create_index("ix_learning_observations_user_observed", _TABLE, ["user_id", "observed_at"])
    op.create_index("ix_learning_observations_user_modality", _TABLE, ["user_id", "modality"])
    op.create_index(
        "ix_learning_observations_user_intervention", _TABLE, ["user_id", "intervention_plan_ref"]
    )


def downgrade() -> None:
    bind = op.get_bind()
    if _TABLE not in set(sa.inspect(bind).get_table_names()):
        return
    op.drop_table(_TABLE)
