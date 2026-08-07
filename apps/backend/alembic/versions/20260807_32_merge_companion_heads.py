"""Merge the contrast-card and companion-session migration heads.

The two features were developed independently and both initially selected a
``20260806_30`` revision family.  This explicit no-op merge keeps existing
databases upgradeable while giving subsequent companion migrations one head.
"""

revision = "20260807_32_merge_heads"
down_revision = ("20260806_30", "20260806_30_companion")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
