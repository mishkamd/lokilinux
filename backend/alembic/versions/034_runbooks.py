"""runbooks — incident_type -> Workflow bridge.

Task E2, Observability & Event Intelligence plan (Phase E: Topology + Runbooks).
A runbook is a thin mapping row; execution reuses the existing Workflow
Engine (services/workflow_engine.py::start_run) end to end — no duplicated
execution logic.

Revision ID: 034
Create Date: 2026-08-25
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "034"
down_revision = "033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "runbooks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", sa.Text(), nullable=False, server_default="default"),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("incident_type", sa.Text(), nullable=False),
        sa.Column("workflow_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workflows.id", ondelete="SET NULL")),
        sa.Column("trigger_mode", sa.Text(), nullable=False, server_default="MANUAL"),  # MANUAL|AUTO
        sa.Column("min_severity", sa.Text(), nullable=False, server_default="HIGH"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", postgresql.UUID(as_uuid=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("tenant_id", "incident_type", "name", name="uq_runbooks_tenant_type_name"),
    )


def downgrade() -> None:
    op.drop_table("runbooks")
