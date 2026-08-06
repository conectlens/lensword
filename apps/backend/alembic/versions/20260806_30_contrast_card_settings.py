"""Add the independently gated contrast-card setting (issue #206)."""

from alembic import op
import sqlalchemy as sa

revision = "20260806_30"
down_revision = "20260806_29"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "recall_settings" not in tables:
        return
    existing = {column["name"] for column in inspector.get_columns("recall_settings")}
    if "contrast_cards_enabled" not in existing:
        op.add_column(
            "recall_settings",
            sa.Column("contrast_cards_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
    if "contrast_min_stability" not in existing:
        op.add_column(
            "recall_settings",
            sa.Column("contrast_min_stability", sa.Float(), nullable=False, server_default="21.0"),
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "recall_settings" not in set(inspector.get_table_names()):
        return
    existing = {column["name"] for column in inspector.get_columns("recall_settings")}
    with op.batch_alter_table("recall_settings") as batch:
        if "contrast_min_stability" in existing:
            batch.drop_column("contrast_min_stability")
        if "contrast_cards_enabled" in existing:
            batch.drop_column("contrast_cards_enabled")
