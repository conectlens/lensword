"""Create immutable weekly learning report snapshots.

Revision ID: 20260730_05
Revises: 20260730_04
"""
from alembic import op
import sqlalchemy as sa

revision = "20260730_05"
down_revision = "20260730_04"
branch_labels = None
depends_on = None

def upgrade() -> None:
    if "weekly_learning_reports" in set(sa.inspect(op.get_bind()).get_table_names()): return
    op.create_table("weekly_learning_reports", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False), sa.Column("week_start", sa.DateTime(), nullable=False), sa.Column("week_end", sa.DateTime(), nullable=False), sa.Column("time_zone", sa.String(length=64), nullable=False), sa.Column("snapshot", sa.JSON(), nullable=False), sa.Column("narration", sa.Text(), nullable=True), sa.Column("created_at", sa.DateTime(), nullable=False))
    op.create_index("ix_weekly_learning_reports_user_id", "weekly_learning_reports", ["user_id"])

def downgrade() -> None:
    if "weekly_learning_reports" in set(sa.inspect(op.get_bind()).get_table_names()):
        op.drop_index("ix_weekly_learning_reports_user_id", table_name="weekly_learning_reports")
        op.drop_table("weekly_learning_reports")
