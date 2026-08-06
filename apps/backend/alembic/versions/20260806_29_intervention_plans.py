"""Add intervention_plans and intervention_outcomes (issue #185 TODO 0/4).

Revision ID: 20260806_29
Revises: 20260806_28

Append-only stores of a diagnosis-to-intervention plan and whether it was
carried out, mirroring diagnoses' own table shape (20260806_25).
"""
from alembic import op
import sqlalchemy as sa

revision = "20260806_29"
down_revision = "20260806_28"
branch_labels = None
depends_on = None

_PLANS_TABLE = "intervention_plans"
_OUTCOMES_TABLE = "intervention_outcomes"


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())

    if _PLANS_TABLE not in tables:
        op.create_table(
            _PLANS_TABLE,
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("word_id", sa.Integer(), sa.ForeignKey("words.id"), nullable=False),
            sa.Column("diagnosis_outcome", sa.String(48), nullable=False),
            sa.Column("strategy", sa.String(48), nullable=False),
            sa.Column("policy_version", sa.Integer(), nullable=False),
            sa.Column("eligible", sa.Boolean(), nullable=False),
            sa.Column("rationale", sa.String(500), nullable=False),
            sa.Column("planned_at", sa.DateTime(), nullable=False),
            sa.Column("scheduled_for", sa.DateTime(), nullable=True),
        )
        op.create_index(
            "ix_intervention_plans_user_word_planned",
            _PLANS_TABLE,
            ["user_id", "word_id", "planned_at"],
        )

    if _OUTCOMES_TABLE not in tables:
        op.create_table(
            _OUTCOMES_TABLE,
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("word_id", sa.Integer(), sa.ForeignKey("words.id"), nullable=False),
            sa.Column("strategy", sa.String(48), nullable=False),
            sa.Column("completed", sa.Boolean(), nullable=False),
            sa.Column("result", sa.String(48), nullable=False),
            sa.Column("recorded_at", sa.DateTime(), nullable=False),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
        )
        op.create_index(
            "ix_intervention_outcomes_user_word_recorded",
            _OUTCOMES_TABLE,
            ["user_id", "word_id", "recorded_at"],
        )


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if _OUTCOMES_TABLE in tables:
        op.drop_table(_OUTCOMES_TABLE)
    if _PLANS_TABLE in tables:
        op.drop_table(_PLANS_TABLE)
