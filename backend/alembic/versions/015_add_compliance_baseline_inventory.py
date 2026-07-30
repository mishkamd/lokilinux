"""Add Baseline Manager + Inventory Collector tables (Compliance module, Phase 1).

Revision ID: 015
Create Date: 2026-07-28

First slice of the Infrastructure Compliance & Drift Management module
(docs/compliance/). Scope matches the Phase 1 roadmap entry in
docs/compliance/13-OPS.md: Baseline Manager scope-tree + versioning, and the
content-addressable Inventory Collector storage. Policy Engine, Drift
Detection, Remediation, and AI tables land in later migrations as their
phases are built, per docs/compliance/01-DATA-MODEL.md.

Conventions matched from the existing schema (models/policy.py, models/job.py):
UUID PK via gen_random_uuid() for top-level entities, Integer autoincrement PK
for log/join tables, String status columns (no native PG ENUM), created_by/
changed_by as bare UUID with no FK (Better Auth owns users, not this schema).

inventory_deltas is a TimescaleDB hypertable, space-partitioned on agent_id
(16 partitions) in addition to time, matching the agent_metrics hypertable
recipe already proven in 001_initial_schema.py.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "015"
down_revision = "013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Baseline Manager ──────────────────────────────────────────────────
    op.create_table(
        "baselines",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("scope_type", sa.String(20), nullable=False),
        sa.Column("scope_selector", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("parent_baseline_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("baselines.id")),
        sa.Column("is_enabled", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("created_by", postgresql.UUID(as_uuid=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_baselines_scope_type", "baselines", ["scope_type"])
    op.create_index("ix_baselines_scope_selector_gin", "baselines", ["scope_selector"], postgresql_using="gin")
    op.create_index("ix_baselines_parent", "baselines", ["parent_baseline_id"])

    op.create_table(
        "baseline_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("baseline_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("baselines.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="DRAFT"),
        sa.Column("expected_state", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("signature", postgresql.BYTEA),
        sa.Column("signed_by", postgresql.UUID(as_uuid=True)),
        sa.Column("change_summary", sa.Text),
        sa.Column("created_by", postgresql.UUID(as_uuid=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("deprecated_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("baseline_id", "version", name="uq_baseline_versions_baseline_version"),
    )
    op.create_index("ix_baseline_versions_baseline_status", "baseline_versions", ["baseline_id", "status"])
    op.create_index("ix_baseline_versions_content_hash", "baseline_versions", ["content_hash"])

    op.create_table(
        "baseline_approvals",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("baseline_version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("baseline_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("approver_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("decision", sa.String(20), nullable=False),
        sa.Column("comment", sa.Text),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_baseline_approvals_version", "baseline_approvals", ["baseline_version_id"])

    # Materialized "effective baseline per agent" cache — recomputable from
    # baselines + baseline_versions, not a source of truth. See
    # docs/compliance/06-BASELINE.md for the merge algorithm.
    op.create_table(
        "baseline_effective",
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("baseline_version_ids", postgresql.ARRAY(postgresql.UUID(as_uuid=True)), nullable=False),
        sa.Column("merged_state", postgresql.JSONB, nullable=False),
        sa.Column("merged_hash", sa.String(64), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    # ── Inventory Collector (content-addressable) ─────────────────────────
    op.create_table(
        "inventory_blobs",
        sa.Column("content_hash", sa.String(64), primary_key=True),
        sa.Column("body", postgresql.BYTEA, nullable=False),
        sa.Column("algo", sa.String(20), nullable=False, server_default="blake3"),
        sa.Column("size_bytes", sa.Integer, nullable=False),
        sa.Column("ref_count", sa.Integer, nullable=False, server_default="1"),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "inventory_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("domain", sa.String(50), nullable=False),
        sa.Column("content_hash", sa.String(64), sa.ForeignKey("inventory_blobs.content_hash"), nullable=False),
        sa.Column("taken_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_inv_snapshots_agent_domain_time", "inventory_snapshots", ["agent_id", "domain", sa.text("taken_at DESC")])
    op.create_index(
        "ix_inv_snapshots_dedup", "inventory_snapshots",
        ["agent_id", "domain", "content_hash", "taken_at"], unique=True,
    )

    # TimescaleDB hypertable, space-partitioned on agent_id (16 partitions) —
    # same recipe as agent_metrics in 001_initial_schema.py.
    op.create_table(
        "inventory_deltas",
        sa.Column("time", sa.DateTime(timezone=True), nullable=False, primary_key=True),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False, primary_key=True),
        sa.Column("domain", sa.String(50), nullable=False, primary_key=True),
        sa.Column("prev_hash", sa.String(64)),
        sa.Column("new_hash", sa.String(64), nullable=False),
        sa.Column("diff", postgresql.JSONB),
    )
    op.execute(
        "SELECT create_hypertable('inventory_deltas', 'time', if_not_exists => TRUE, "
        "partitioning_column => 'agent_id', number_partitions => 16)"
    )
    op.create_index("ix_inv_deltas_agent_time", "inventory_deltas", ["agent_id", sa.text("time DESC")])
    op.execute(
        "ALTER TABLE inventory_deltas SET (timescaledb.compress, timescaledb.compress_segmentby = 'agent_id')"
    )
    op.execute("SELECT add_compression_policy('inventory_deltas', INTERVAL '7 days')")
    op.execute("SELECT add_retention_policy('inventory_deltas', INTERVAL '90 days')")


def downgrade() -> None:
    op.execute("SELECT remove_retention_policy('inventory_deltas', if_exists => TRUE)")
    op.execute("SELECT remove_compression_policy('inventory_deltas', if_exists => TRUE)")
    op.drop_table("inventory_deltas")
    op.drop_index("ix_inv_snapshots_dedup", table_name="inventory_snapshots")
    op.drop_index("ix_inv_snapshots_agent_domain_time", table_name="inventory_snapshots")
    op.drop_table("inventory_snapshots")
    op.drop_table("inventory_blobs")

    op.drop_table("baseline_effective")
    op.drop_index("ix_baseline_approvals_version", table_name="baseline_approvals")
    op.drop_table("baseline_approvals")
    op.drop_index("ix_baseline_versions_content_hash", table_name="baseline_versions")
    op.drop_index("ix_baseline_versions_baseline_status", table_name="baseline_versions")
    op.drop_table("baseline_versions")
    op.drop_index("ix_baselines_parent", table_name="baselines")
    op.drop_index("ix_baselines_scope_selector_gin", table_name="baselines")
    op.drop_index("ix_baselines_scope_type", table_name="baselines")
    op.drop_table("baselines")
