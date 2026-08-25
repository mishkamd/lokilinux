"""incidents/incident_signals/incident_timeline tables + alerts.incident_id link.

Task D1, Observability & Event Intelligence plan (Phase D: Incident Engine).
Incidents ALSO create an Alert through the existing AlertService (Task D2's
bridge) — this column is what links the two without changing anything about
how /alerts already works.

Revision ID: 032
Create Date: 2026-08-25
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "032"
down_revision = "031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "incidents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", sa.Text(), nullable=False, server_default="default"),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="OPEN"),
        sa.Column("root_cause_signal_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("signals.id", ondelete="SET NULL")),
        sa.Column("confidence", sa.Float()),
        sa.Column("group_key", sa.Text()),
        sa.Column("correlation_rule_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("correlation_rules.id", ondelete="SET NULL")),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True)),
        sa.Column("metadata", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.create_index("ix_incidents_open", "incidents", ["tenant_id", "status"])
    op.create_index("ix_incidents_group_key", "incidents", ["tenant_id", "group_key"])

    op.create_table(
        "incident_signals",
        sa.Column("incident_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("incidents.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("signal_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("signals.id", ondelete="CASCADE"), primary_key=True),
    )

    op.create_table(
        "incident_timeline",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("incident_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("ts", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),  # created|signal|transition|runbook|note
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    )

    op.add_column("alerts", sa.Column("incident_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("incidents.id", ondelete="SET NULL"), nullable=True))


def downgrade() -> None:
    op.drop_column("alerts", "incident_id")
    op.drop_table("incident_timeline")
    op.drop_table("incident_signals")
    op.drop_index("ix_incidents_group_key", table_name="incidents")
    op.drop_index("ix_incidents_open", table_name="incidents")
    op.drop_table("incidents")
