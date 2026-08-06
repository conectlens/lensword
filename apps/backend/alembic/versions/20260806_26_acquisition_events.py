"""Persist the graduated acquisition ladder (AI Learning Diagnosis epic, issue #184).

Revision ID: 20260806_26
Revises: 20260806_25

Append-only, the same reasoning as diagnoses (#183), learning_observations
(#182) and knowledge_edges (#203): a rung transition is a new row, never a
rewrite of the one before it. "The current state" is the most recent row
for (user_id, word_id) — there is no separate mutable state table.
"""
from alembic import op
import sqlalchemy as sa

revision = "20260806_26"
down_revision = "20260806_25"
branch_labels = None
depends_on = None

_TABLE = "acquisition_events"


def upgrade() -> None:
    bind = op.get_bind()
    if _TABLE in set(sa.inspect(bind).get_table_names()):
        return

    op.create_table(
        _TABLE,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("word_id", sa.Integer(), sa.ForeignKey("words.id"), nullable=False),
        sa.Column("rung", sa.Integer(), nullable=False),
        sa.Column("ladder_version", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("graduated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("due_at", sa.DateTime(), nullable=False),
        sa.Column("entry_reason", sa.String(length=32), nullable=True),
        sa.Column("operation_id", sa.String(length=64), nullable=True),
    )
    op.create_unique_constraint(
        "uq_acquisition_event_user_operation", _TABLE, ["user_id", "operation_id"]
    )
    op.create_index(
        "ix_acquisition_events_user_word_updated", _TABLE, ["user_id", "word_id", "updated_at"]
    )
    op.create_index("ix_acquisition_events_due", _TABLE, ["graduated", "due_at"])


def downgrade() -> None:
    bind = op.get_bind()
    if _TABLE not in set(sa.inspect(bind).get_table_names()):
        return
    op.drop_table(_TABLE)
