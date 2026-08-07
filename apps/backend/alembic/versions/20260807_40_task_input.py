"""Add bounded execution input to companion tasks (#197).

The background executor (app.infrastructure.jobs.companion_task_dispatch)
needs to know *what* an EXTRACTION or PLAN_GENERATION task should do without
re-deriving it mid-run — this column carries the bounded, already-authorized
parameters the task was created with (precomputed extraction candidates, or
the due-word items a plan should cover).
"""

from alembic import op
import sqlalchemy as sa

revision = "20260807_40_task_input"
down_revision = "20260807_38_companion_loop"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("companion_tasks")}
    if "input" in columns:
        return
    op.add_column("companion_tasks", sa.Column("input", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("companion_tasks") as batch_op:
        batch_op.drop_column("input")
