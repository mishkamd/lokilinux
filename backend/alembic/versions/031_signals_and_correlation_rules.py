"""signals + correlation_rules tables — event-derived operational state.

Task B1, Observability & Event Intelligence plan (Phase B: Signal Engine).
signals = one row per (tenant_id, fingerprint), upserted by SignalService as
occurrences arrive (raw occurrences live in ClickHouse, see Task A1).
correlation_rules = weighted-window rules the correlation evaluator (Phase C)
matches signals against to open incidents.

Revision ID: 031
Create Date: 2026-08-25
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "031"
down_revision = "030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "signals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", sa.Text(), nullable=False, server_default="default"),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="OPEN"),
        sa.Column("host_id", postgresql.UUID(as_uuid=True)),
        sa.Column("service", sa.Text()),
        sa.Column("fingerprint", sa.Text(), nullable=False),
        sa.Column("occurrence_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_event_id", postgresql.UUID(as_uuid=True)),
        sa.Column("metadata", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.UniqueConstraint("tenant_id", "fingerprint", name="uq_signals_tenant_fingerprint"),
    )
    op.create_index("ix_signals_open", "signals", ["status", "severity"])

    op.create_table(
        "correlation_rules",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", sa.Text(), nullable=False, server_default="default"),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("window_seconds", sa.Integer(), nullable=False, server_default="300"),
        sa.Column("group_by", postgresql.JSONB, nullable=False),
        sa.Column("conditions", postgresql.JSONB, nullable=False),
        sa.Column("threshold_score", sa.Integer(), nullable=False),
        sa.Column("incident_type", sa.Text(), nullable=False),
        sa.Column("incident_severity", sa.Text(), nullable=False),
        sa.Column("suppressions", postgresql.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("tenant_id", "name", name="uq_corr_rules_tenant_name"),
    )


def downgrade() -> None:
    op.drop_table("correlation_rules")
    op.drop_index("ix_signals_open", table_name="signals")
    op.drop_table("signals")
