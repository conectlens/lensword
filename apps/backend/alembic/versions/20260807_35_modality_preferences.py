"""Add modality_preferences (issue #186 TODO 0).

Revision ID: 20260807_35
Revises: 20260807_34

A learner's stated modality preference ("I like images"), kept append-only
and in its own table so it can never be conflated with the
LearningObservation/InterventionOutcome-derived effectiveness
`intervention_efficacy.py` computes — see that module's own docstring for
why the two must never merge.
"""
from alembic import op
import sqlalchemy as sa

revision = "20260807_35"
down_revision = "20260807_34"
branch_labels = None
depends_on = None

_TABLE = "modality_preferences"


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if _TABLE not in tables:
        op.create_table(
            _TABLE,
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("modality", sa.String(32), nullable=False),
            sa.Column("stated_at", sa.DateTime(), nullable=False),
        )
        op.create_index(
            "ix_modality_preferences_user_stated",
            _TABLE,
            ["user_id", "stated_at"],
        )


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if _TABLE in tables:
        op.drop_table(_TABLE)
