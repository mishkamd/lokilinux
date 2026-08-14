"""Compliance Engine completion: exceptions, framework mappings, resource
dependency index, assessment jobs, drift lifecycle, evidence, versioned
policy sets.

Revision ID: 025
Revises: 024
Create Date: 2026-08-13

Single additive revision closing the gaps identified against the Compliance
Engine brief — no drops, no rewrites of existing hypertable data.

- compliance_exceptions: waivers (docs/compliance §17). agent_id XOR
  scope_selector — a NULL agent_id means the exception applies via selector,
  same scope-tree convention as policy_assignments/baselines.
- compliance_frameworks/framework_versions/controls/rule_mappings: proper
  many-to-many framework mapping (§19) rather than only the JSONB
  standard_refs already on compliance_rules — standard_refs stays as the
  raw import source, these tables are the queryable normalization of it.
- compliance_rule_resources: resource -> rule dependency index (§40) so an
  incremental file-change evaluation can look up "which rules does this
  path affect" without scanning the whole catalog.
- compliance_assessments: async fleet assessment job tracking (§24).
- drift_events gains a lifecycle (§9) and correlation/dedup columns (§9,
  §39): ADD COLUMN only — hypertables tolerate this across all chunks,
  same as file_hashes' mode/uid/gid landing after its hypertable already had
  data in migration 017.
- rule_evaluations gains evidence/exception columns (§4, §17, §21).
- file_changes gains old/new mode+uid+gid so file_integrity_collector's planned
  PERMISSION_CHANGED/OWNER_CHANGED (migration 017's TODO in
  services/compliance/internal/ingest/file_integrity.go) has somewhere to land.
- policy_sets gains flat version/publish columns, mirroring baselines'
  immutable-once-published rule (§6) without a second version table: editing
  a PUBLISHED set clones a new policy_sets row via parent_policy_set_id.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "025"
down_revision = "024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Exceptions / waivers ──────────────────────────────────────────────
    op.create_table(
        "compliance_exceptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("rule_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("compliance_rules.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agents.id", ondelete="CASCADE")),
        sa.Column("scope_selector", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("owner", sa.String(255), nullable=False),
        sa.Column("requested_by", postgresql.UUID(as_uuid=True)),
        sa.Column("approved_by", postgresql.UUID(as_uuid=True)),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),  # PENDING/ACTIVE/EXPIRED/REVOKED
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_compliance_exceptions_rule", "compliance_exceptions", ["rule_id"])
    op.create_index("ix_compliance_exceptions_agent", "compliance_exceptions", ["agent_id"])
    op.create_index(
        "ix_compliance_exceptions_active_expiry", "compliance_exceptions", ["expires_at"],
        postgresql_where=sa.text("status = 'ACTIVE'"),
    )

    # ── Framework mappings ────────────────────────────────────────────────
    op.create_table(
        "compliance_frameworks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("key", sa.String(30), nullable=False, unique=True),  # CIS/NIST/STIG/PCI_DSS/ISO27001/INTERNAL/...
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "compliance_framework_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("framework_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("compliance_frameworks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.String(50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("framework_id", "version", name="uq_framework_versions_framework_version"),
    )

    op.create_table(
        "compliance_controls",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("framework_version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("compliance_framework_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("control_id", sa.String(100), nullable=False),  # e.g. "5.2.1"
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("description", sa.Text),
        sa.UniqueConstraint("framework_version_id", "control_id", name="uq_controls_framework_version_control"),
    )

    op.create_table(
        "compliance_rule_mappings",
        sa.Column("rule_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("compliance_rules.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("control_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("compliance_controls.id", ondelete="CASCADE"), primary_key=True),
    )

    # ── Resource -> rule dependency index ─────────────────────────────────
    op.create_table(
        "compliance_rule_resources",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("rule_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("compliance_rules.id", ondelete="CASCADE"), nullable=False),
        sa.Column("resource_type", sa.String(30), nullable=False),  # FILE/PACKAGE/SERVICE/SYSCTL_KEY/...
        sa.Column("resource_path", sa.String(1000), nullable=False),
        sa.UniqueConstraint("rule_id", "resource_type", "resource_path", name="uq_rule_resources_rule_type_path"),
    )
    op.create_index("ix_rule_resources_lookup", "compliance_rule_resources", ["resource_type", "resource_path"])

    # ── Async fleet assessments ────────────────────────────────────────────
    op.create_table(
        "compliance_assessments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("scope_selector", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("policy_set_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("policy_sets.id", ondelete="SET NULL")),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),  # PENDING/RUNNING/COMPLETED/FAILED/CANCELLED
        sa.Column("servers_total", sa.Integer, nullable=False, server_default="0"),
        sa.Column("servers_done", sa.Integer, nullable=False, server_default="0"),
        sa.Column("rules_total", sa.Integer, nullable=False, server_default="0"),
        sa.Column("rules_done", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_compliance_assessments_status", "compliance_assessments", ["status"])

    # ── Drift lifecycle + dedup (hypertable, ADD COLUMN only) ─────────────
    op.add_column("drift_events", sa.Column("status", sa.String(20), nullable=False, server_default="OPEN"))
    op.add_column("drift_events", sa.Column("occurrences", sa.Integer, nullable=False, server_default="1"))
    op.add_column("drift_events", sa.Column("first_seen", sa.DateTime(timezone=True)))
    op.add_column("drift_events", sa.Column("last_seen", sa.DateTime(timezone=True)))
    op.add_column("drift_events", sa.Column("correlation_key", sa.String(64)))
    op.add_column("drift_events", sa.Column("resolved_at", sa.DateTime(timezone=True)))
    op.add_column("drift_events", sa.Column("suppressed_by", postgresql.UUID(as_uuid=True)))
    op.execute("UPDATE drift_events SET first_seen = time, last_seen = time WHERE first_seen IS NULL")
    op.create_index(
        "ix_drift_events_correlation", "drift_events", ["agent_id", "correlation_key", "status"],
    )

    # ── Evaluation evidence + exception linkage ────────────────────────────
    op.add_column("rule_evaluations", sa.Column("expected_value", postgresql.JSONB))
    op.add_column("rule_evaluations", sa.Column("evidence_hash", sa.String(64)))
    op.add_column("rule_evaluations", sa.Column("source", sa.String(50)))
    op.add_column("rule_evaluations", sa.Column("agent_version", sa.String(50)))
    op.add_column("rule_evaluations", sa.Column("exception_id", postgresql.UUID(as_uuid=True)))

    # ── File integrity: permission/owner change columns ────────────────────
    op.add_column("file_changes", sa.Column("old_mode", sa.Integer))
    op.add_column("file_changes", sa.Column("new_mode", sa.Integer))
    op.add_column("file_changes", sa.Column("old_uid", sa.Integer))
    op.add_column("file_changes", sa.Column("new_uid", sa.Integer))
    op.add_column("file_changes", sa.Column("old_gid", sa.Integer))
    op.add_column("file_changes", sa.Column("new_gid", sa.Integer))

    # ── Policy sets: flat immutable versioning ──────────────────────────────
    op.add_column("policy_sets", sa.Column("status", sa.String(20), nullable=False, server_default="PUBLISHED"))  # DRAFT/PUBLISHED/ARCHIVED
    op.add_column("policy_sets", sa.Column("published_at", sa.DateTime(timezone=True)))
    op.add_column("policy_sets", sa.Column("published_version", sa.Integer, nullable=False, server_default="1"))
    op.add_column("policy_sets", sa.Column("parent_policy_set_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("policy_sets.id")))
    op.execute("UPDATE policy_sets SET published_at = created_at WHERE published_at IS NULL")


def downgrade() -> None:
    op.drop_column("policy_sets", "parent_policy_set_id")
    op.drop_column("policy_sets", "published_version")
    op.drop_column("policy_sets", "published_at")
    op.drop_column("policy_sets", "status")

    op.drop_column("file_changes", "new_gid")
    op.drop_column("file_changes", "old_gid")
    op.drop_column("file_changes", "new_uid")
    op.drop_column("file_changes", "old_uid")
    op.drop_column("file_changes", "new_mode")
    op.drop_column("file_changes", "old_mode")

    op.drop_column("rule_evaluations", "exception_id")
    op.drop_column("rule_evaluations", "agent_version")
    op.drop_column("rule_evaluations", "source")
    op.drop_column("rule_evaluations", "evidence_hash")
    op.drop_column("rule_evaluations", "expected_value")

    op.drop_index("ix_drift_events_correlation", table_name="drift_events")
    op.drop_column("drift_events", "suppressed_by")
    op.drop_column("drift_events", "resolved_at")
    op.drop_column("drift_events", "correlation_key")
    op.drop_column("drift_events", "last_seen")
    op.drop_column("drift_events", "first_seen")
    op.drop_column("drift_events", "occurrences")
    op.drop_column("drift_events", "status")

    op.drop_index("ix_compliance_assessments_status", table_name="compliance_assessments")
    op.drop_table("compliance_assessments")

    op.drop_index("ix_rule_resources_lookup", table_name="compliance_rule_resources")
    op.drop_table("compliance_rule_resources")

    op.drop_table("compliance_rule_mappings")
    op.drop_table("compliance_controls")
    op.drop_table("compliance_framework_versions")
    op.drop_table("compliance_frameworks")

    op.drop_index("ix_compliance_exceptions_active_expiry", table_name="compliance_exceptions")
    op.drop_index("ix_compliance_exceptions_agent", table_name="compliance_exceptions")
    op.drop_index("ix_compliance_exceptions_rule", table_name="compliance_exceptions")
    op.drop_table("compliance_exceptions")
