"""Create adaptive practice persistence.

Revision ID: 20260730_04
Revises: 20260730_03
Create Date: 2026-07-30
"""
from alembic import op
import sqlalchemy as sa

revision = "20260730_04"
down_revision = "20260730_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "practice_exercises" not in tables:
        op.create_table(
        "practice_exercises",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("word_id", sa.Integer(), sa.ForeignKey("words.id"), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("options", sa.JSON(), nullable=False),
        sa.Column("answered", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("correct", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_practice_exercises_user_id", "practice_exercises", ["user_id"])
        op.create_index("ix_practice_exercises_word_id", "practice_exercises", ["word_id"])
    if "daily_session_preferences" not in tables:
        op.create_table(
        "daily_session_preferences",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("goal_minutes", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("review_limit", sa.Integer(), nullable=False, server_default="20"),
        )


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "daily_session_preferences" in tables:
        op.drop_table("daily_session_preferences")
    if "practice_exercises" in tables:
        op.drop_index("ix_practice_exercises_word_id", table_name="practice_exercises")
        op.drop_index("ix_practice_exercises_user_id", table_name="practice_exercises")
        op.drop_table("practice_exercises")
