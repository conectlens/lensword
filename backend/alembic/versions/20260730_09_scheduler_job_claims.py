"""Claims that make a scheduled job fire once across concurrent instances.

Revision ID: 20260730_09
Revises: 20260730_08
"""
from alembic import op
import sqlalchemy as sa

revision = "20260730_09"
down_revision = "20260730_08"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "scheduler_job_claims" not in set(sa.inspect(op.get_bind()).get_table_names()):
        op.create_table(
            "scheduler_job_claims",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("job_key", sa.String(128), nullable=False),
            sa.Column("occurrence_key", sa.String(64), nullable=False),
            sa.Column("claimed_at", sa.DateTime(), nullable=False),
            # The exclusivity mechanism itself, not merely an integrity nicety:
            # concurrent instances all insert this row and exactly one wins.
            sa.UniqueConstraint("job_key", "occurrence_key", name="uq_scheduler_job_occurrence"),
        )
        op.create_index("ix_scheduler_job_claims_job_key", "scheduler_job_claims", ["job_key"])
        # Claims are pruned by age, so that sweep needs its own index.
        op.create_index("ix_scheduler_job_claims_claimed_at", "scheduler_job_claims", ["claimed_at"])


def downgrade() -> None:
    if "scheduler_job_claims" in set(sa.inspect(op.get_bind()).get_table_names()):
        op.drop_table("scheduler_job_claims")
