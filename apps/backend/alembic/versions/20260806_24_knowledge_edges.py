"""Persist the knowledge graph (issue #138 completion, issue #203).

Revision ID: 20260806_24
Revises: 20260806_23

#138 specified a KnowledgeEdge table and shipped only the domain service
that would populate it — every read recomputed the whole graph from
scratch. This is that table: canonical (lower word id first) so a
relation from build_edges() is one row however it was discovered, unique
on (user_id, source_id, target_id, relation) for the same reason.
"""
from alembic import op
import sqlalchemy as sa

revision = "20260806_24"
down_revision = "20260806_23"
branch_labels = None
depends_on = None

_TABLE = "knowledge_edges"


def upgrade() -> None:
    bind = op.get_bind()
    if _TABLE in set(sa.inspect(bind).get_table_names()):
        return

    op.create_table(
        _TABLE,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("words.id"), nullable=False),
        sa.Column("target_id", sa.Integer(), sa.ForeignKey("words.id"), nullable=False),
        sa.Column("relation", sa.String(length=16), nullable=False),
        sa.Column("strength", sa.Float(), nullable=False),
        sa.Column("evidence", sa.String(length=255), nullable=False),
        sa.Column("occurrences", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_unique_constraint(
        "uq_knowledge_edge", _TABLE, ["user_id", "source_id", "target_id", "relation"]
    )
    op.create_index(
        "ix_knowledge_edges_user_source_strength", _TABLE, ["user_id", "source_id", "strength"]
    )
    op.create_index(
        "ix_knowledge_edges_user_target_strength", _TABLE, ["user_id", "target_id", "strength"]
    )


def downgrade() -> None:
    bind = op.get_bind()
    if _TABLE not in set(sa.inspect(bind).get_table_names()):
        return
    op.drop_table(_TABLE)
