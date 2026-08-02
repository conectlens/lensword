"""Learning paths and their milestones (issue #137).

Revision ID: 20260730_17
Revises: 20260730_16

A goal the learner stated, broken into steps that can be measured.

There is deliberately no progress column on either table. Progress is counted
from the learner's actual vocabulary at read time; a stored percentage is a
number that was true once, and it drifts the moment a word is added or deleted.
A progress bar that disagrees with the vocabulary list beside it is worse than
no progress bar.
"""
from alembic import op
import sqlalchemy as sa

revision = "20260730_17"
down_revision = "20260730_16"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())

    if "learning_paths" not in tables:
        op.create_table(
            "learning_paths",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("group_id", sa.Integer(), sa.ForeignKey("groups.id"), nullable=True),
            sa.Column("goal", sa.String(length=500), nullable=False),
            sa.Column("target_language", sa.String(length=32), nullable=False),
            sa.Column("ai_provider", sa.String(length=64), nullable=True),
            sa.Column("ai_model", sa.String(length=255), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_learning_paths_user_id", "learning_paths", ["user_id"])
        op.create_index("ix_learning_paths_created_at", "learning_paths", ["created_at"])

    if "path_milestones" not in tables:
        op.create_table(
            "path_milestones",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "path_id", sa.Integer(), sa.ForeignKey("learning_paths.id"), nullable=False
            ),
            sa.Column("position", sa.Integer(), nullable=False),
            sa.Column("title", sa.String(length=120), nullable=False),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column("topic", sa.String(length=64), nullable=False),
            sa.Column("target_word_count", sa.Integer(), nullable=False),
            sa.Column("cefr_level", sa.String(length=8), nullable=True),
        )
        op.create_index("ix_path_milestones_path_id", "path_milestones", ["path_id"])
        op.create_index("ix_path_milestones_topic", "path_milestones", ["topic"])


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    # Milestones first: they reference the paths.
    if "path_milestones" in tables:
        op.drop_table("path_milestones")
    if "learning_paths" in tables:
        op.drop_table("learning_paths")
