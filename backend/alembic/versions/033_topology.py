"""topology_nodes + topology_edges — dependency graph for incident enrichment.

Task E1, Observability & Event Intelligence plan (Phase E: Topology + Runbooks).

Revision ID: 033
Create Date: 2026-08-25
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "033"
down_revision = "032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "topology_nodes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", sa.Text(), nullable=False, server_default="default"),
        sa.Column("kind", sa.Text(), nullable=False),  # HOST|SERVICE|APPLICATION|EXTERNAL
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agents.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("tenant_id", "kind", "name", name="uq_topology_nodes_tenant_kind_name"),
    )

    op.create_table(
        "topology_edges",
        sa.Column("from_node", postgresql.UUID(as_uuid=True), sa.ForeignKey("topology_nodes.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("to_node", postgresql.UUID(as_uuid=True), sa.ForeignKey("topology_nodes.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("kind", sa.Text(), nullable=False, server_default="DEPENDS_ON"),
    )


def downgrade() -> None:
    op.drop_table("topology_edges")
    op.drop_table("topology_nodes")
