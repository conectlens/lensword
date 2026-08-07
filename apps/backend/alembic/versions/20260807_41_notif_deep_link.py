"""Add a companion deep link to the desktop notification outbox (#197 TODO 0).

Reuses the existing outbox (issue #175/#27) rather than a second notification
path: a due-word or acquisition-ladder notification that fires while AI
Companion is enabled now carries a `lensword://` URI the shell can open into
a prompt or a resumable companion session. Nothing about *whether* or *when*
a notification fires changes — this only adds where "open" goes.
"""

from alembic import op
import sqlalchemy as sa

revision = "20260807_41_notif_deep_link"
down_revision = "20260807_40_task_input"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("desktop_notifications")}
    if "companion_deep_link" in columns:
        return
    op.add_column("desktop_notifications", sa.Column("companion_deep_link", sa.String(255), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("desktop_notifications") as batch_op:
        batch_op.drop_column("companion_deep_link")
