"""Add pair/prerequisite/horizon columns to intervention tables (issue #185).

Revision ID: 20260807_34
Revises: 20260807_33_companion_tasks

TODO 1 needs a diagnosis to name the second word of a confusion pair (so the
planner can stage isolate before contrast) and a plan to carry that pair
forward; TODO 2 needs a plan to record the ranked prerequisite candidates it
chose from; TODO 5 needs an outcome to say which delayed checkpoint
(immediate/24h/7d/next_review) it measures. All additive, nullable-or-
defaulted columns on tables 20260806_25/20260806_29 already created, not new
tables.
"""
from alembic import op
import sqlalchemy as sa

revision = "20260807_34"
down_revision = "20260807_33_companion_tasks"
branch_labels = None
depends_on = None

_DIAGNOSES_TABLE = "diagnoses"
_PLANS_TABLE = "intervention_plans"
_OUTCOMES_TABLE = "intervention_outcomes"


def upgrade() -> None:
    diagnosis_columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns(_DIAGNOSES_TABLE)}
    if "related_word_id" not in diagnosis_columns:
        op.add_column(
            _DIAGNOSES_TABLE,
            sa.Column("related_word_id", sa.Integer(), sa.ForeignKey("words.id"), nullable=True),
        )

    plan_columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns(_PLANS_TABLE)}
    if "second_word_id" not in plan_columns:
        op.add_column(
            _PLANS_TABLE,
            sa.Column("second_word_id", sa.Integer(), sa.ForeignKey("words.id"), nullable=True),
        )
    if "prerequisite_ids" not in plan_columns:
        op.add_column(_PLANS_TABLE, sa.Column("prerequisite_ids", sa.String(200), nullable=True))

    outcome_columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns(_OUTCOMES_TABLE)}
    if "horizon" not in outcome_columns:
        op.add_column(
            _OUTCOMES_TABLE,
            sa.Column("horizon", sa.String(16), nullable=False, server_default="immediate"),
        )


def downgrade() -> None:
    # batch mode keeps the downgrade working for the SQLite development DB.
    outcome_columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns(_OUTCOMES_TABLE)}
    if "horizon" in outcome_columns:
        with op.batch_alter_table(_OUTCOMES_TABLE) as batch:
            batch.drop_column("horizon")

    plan_columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns(_PLANS_TABLE)}
    if "prerequisite_ids" in plan_columns or "second_word_id" in plan_columns:
        with op.batch_alter_table(_PLANS_TABLE) as batch:
            if "prerequisite_ids" in plan_columns:
                batch.drop_column("prerequisite_ids")
            if "second_word_id" in plan_columns:
                batch.drop_column("second_word_id")

    diagnosis_columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns(_DIAGNOSES_TABLE)}
    if "related_word_id" in diagnosis_columns:
        with op.batch_alter_table(_DIAGNOSES_TABLE) as batch:
            batch.drop_column("related_word_id")
