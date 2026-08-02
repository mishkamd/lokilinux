"""Add Drift Detection + File Integrity Monitoring tables (Compliance module, Phase 2/3).

Revision ID: 017
Create Date: 2026-07-29

Third slice of the Infrastructure Compliance & Drift Management module.
drift_events/drift_details/file_changes are TimescaleDB hypertables,
space-partitioned on agent_id (16 partitions) — same recipe as
inventory_deltas/rule_evaluations/compliance_scores in migrations 015/016.

drift_events' primary key is (time, agent_id, id) — not (time, id) — because
TimescaleDB requires the partitioning column to be part of any unique
constraint (including the PK) on a space-partitioned hypertable. Migration
015's initial dry-run caught this exact mistake for this same table shape
(see docs/compliance/01-DATA-MODEL.md §5) — fixed here before it ever
shipped, not after.

file_hashes is a plain (non-hypertable) table: current-state-only, keyed by
(agent_id, path), overwritten in place — the point-in-time history lives in
file_changes, not here.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "017"
down_revision = "016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "drift_events",
        sa.Column("time", sa.DateTime(timezone=True), nullable=False, primary_key=True),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False, primary_key=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("domain", sa.String(50), nullable=False),
        sa.Column("compared_against", sa.String(20), nullable=False),  # BASELINE/PREVIOUS_SNAPSHOT/DESIRED_STATE
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("change_type", sa.String(30), nullable=False),
        sa.Column("summary", sa.Text, nullable=False),
        sa.Column("changed_by_user", sa.String(255)),
        sa.Column("root_cause", postgresql.JSONB),
        sa.Column("acknowledged_by", postgresql.UUID(as_uuid=True)),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True)),
        sa.Column("remediation_plan_id", postgresql.UUID(as_uuid=True)),
    )
    op.execute(
        "SELECT create_hypertable('drift_events', 'time', if_not_exists => TRUE, "
        "partitioning_column => 'agent_id', number_partitions => 16)"
    )
    op.create_index("ix_drift_events_agent_time", "drift_events", ["agent_id", sa.text("time DESC")])
    op.create_index("ix_drift_events_severity", "drift_events", ["severity", sa.text("time DESC")])
    op.execute("ALTER TABLE drift_events SET (timescaledb.compress, timescaledb.compress_segmentby = 'agent_id')")
    op.execute("SELECT add_compression_policy('drift_events', INTERVAL '7 days')")
    op.execute("SELECT add_retention_policy('drift_events', INTERVAL '365 days')")

    op.create_table(
        "drift_details",
        sa.Column("time", sa.DateTime(timezone=True), nullable=False, primary_key=True),
        sa.Column("drift_event_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("drift_event_id", postgresql.UUID(as_uuid=True), nullable=False, primary_key=True),
        sa.Column("field_path", sa.String(500), nullable=False, primary_key=True),
        sa.Column("old_value", postgresql.JSONB),
        sa.Column("new_value", postgresql.JSONB),
    )
    op.execute("SELECT create_hypertable('drift_details', 'time', if_not_exists => TRUE)")

    op.create_table(
        "file_hashes",
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("path", sa.String(1000), primary_key=True),
        sa.Column("algo", sa.String(10), nullable=False, server_default="sha256"),
        sa.Column("hash", sa.String(128), nullable=False),
        sa.Column("mode", sa.Integer),
        sa.Column("uid", sa.Integer),
        sa.Column("gid", sa.Integer),
        sa.Column("size_bytes", sa.BigInteger),
        sa.Column("mtime", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_file_hashes_hash", "file_hashes", ["hash"])

    op.create_table(
        "file_changes",
        sa.Column("time", sa.DateTime(timezone=True), nullable=False, primary_key=True),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False, primary_key=True),
        sa.Column("path", sa.String(1000), nullable=False, primary_key=True),
        sa.Column("old_hash", sa.String(128)),
        sa.Column("new_hash", sa.String(128)),
        sa.Column("change_kind", sa.String(20), nullable=False),  # CREATED/MODIFIED/DELETED/PERMISSION_CHANGED
    )
    op.execute(
        "SELECT create_hypertable('file_changes', 'time', if_not_exists => TRUE, "
        "partitioning_column => 'agent_id', number_partitions => 16)"
    )
    op.execute("ALTER TABLE file_changes SET (timescaledb.compress, timescaledb.compress_segmentby = 'agent_id')")
    op.execute("SELECT add_compression_policy('file_changes', INTERVAL '7 days')")
    op.execute("SELECT add_retention_policy('file_changes', INTERVAL '365 days')")

    op.create_table(
        "file_integrity_ignores",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("scope_type", sa.String(20), nullable=False, server_default="GLOBAL"),
        sa.Column("scope_selector", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("path_pattern", sa.String(1000), nullable=False),
        sa.Column("reason", sa.Text),
        sa.Column("created_by", postgresql.UUID(as_uuid=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )


def downgrade() -> None:
    op.drop_table("file_integrity_ignores")

    op.execute("SELECT remove_retention_policy('file_changes', if_exists => TRUE)")
    op.execute("SELECT remove_compression_policy('file_changes', if_exists => TRUE)")
    op.drop_table("file_changes")

    op.drop_index("ix_file_hashes_hash", table_name="file_hashes")
    op.drop_table("file_hashes")

    op.drop_table("drift_details")

    op.execute("SELECT remove_retention_policy('drift_events', if_exists => TRUE)")
    op.execute("SELECT remove_compression_policy('drift_events', if_exists => TRUE)")
    op.drop_index("ix_drift_events_severity", table_name="drift_events")
    op.drop_index("ix_drift_events_agent_time", table_name="drift_events")
    op.drop_table("drift_events")
