"""Persist observation corrections (AI Learning Diagnosis epic, issue #229 TODO 5).

Revision ID: 20260806_27
Revises: 20260806_26

A learner's flag on a previously recorded observation — misgraded or
irrelevant — kept as a new row referencing the observation it corrects by
id rather than an edit to it, the same append-only reasoning as
learning_observations (20260806_23) and every other evidence table in
this epic.

The unique constraint on observation_id caps this at one correction per
observation: flagging is a yes/no fact about a recorded row, not itself a
thing worth a history of.
"""
from alembic import op
import sqlalchemy as sa

revision = "20260806_27"
down_revision = "20260806_26"
branch_labels = None
depends_on = None

_TABLE = "observation_corrections"


def upgrade() -> None:
    bind = op.get_bind()
    if _TABLE in set(sa.inspect(bind).get_table_names()):
        return

    op.create_table(
        _TABLE,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("correction_id", sa.String(length=64), nullable=False, unique=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "observation_id",
            sa.String(length=64),
            sa.ForeignKey("learning_observations.observation_id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("reason", sa.String(length=16), nullable=False),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_observation_corrections_correction_id", _TABLE, ["correction_id"])
    op.create_index("ix_observation_corrections_user_id", _TABLE, ["user_id"])
    op.create_index("ix_observation_corrections_observation_id", _TABLE, ["observation_id"])
    op.create_index("ix_observation_corrections_created_at", _TABLE, ["created_at"])


def downgrade() -> None:
    bind = op.get_bind()
    if _TABLE not in set(sa.inspect(bind).get_table_names()):
        return
    op.drop_table(_TABLE)
