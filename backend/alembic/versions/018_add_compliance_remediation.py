"""Add Remediation Engine tables (Compliance module, Phase 3).

Revision ID: 018
Create Date: 2026-07-29

Fourth slice of the Infrastructure Compliance & Drift Management module.
Remediation does not build its own dispatch mechanism — remediation_jobs is
a thin join table recording which existing `jobs` row a plan's approval
created, exactly mirroring how AgentVulnerability.remediation_job_id already
links a CVE finding to a job (models/cve.py). Dedup, per-agent fan-out,
and status aggregation are 100% JobService's existing job (services/job_service.py) —
see docs/compliance/09-REMEDIATION.md.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "018"
down_revision = "017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "maintenance_windows",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("scope_type", sa.String(20), nullable=False, server_default="GLOBAL"),
        sa.Column("scope_selector", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("cron_expr", sa.String(100)),
        sa.Column("duration_minutes", sa.Integer, nullable=False),
        sa.Column("timezone", sa.String(50), nullable=False, server_default="UTC"),
        sa.Column("is_enabled", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "remediation_plans",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="DRAFT"),
        sa.Column("trigger_type", sa.String(20), nullable=False),  # MANUAL/SCHEDULED/AUTOMATIC/AI_SUGGESTED
        sa.Column("maintenance_window_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("maintenance_windows.id")),
        sa.Column("is_emergency", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("created_by", postgresql.UUID(as_uuid=True)),
        sa.Column("approved_by", postgresql.UUID(as_uuid=True)),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_remediation_plans_status", "remediation_plans", ["status"])

    op.create_table(
        "remediation_actions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("remediation_plan_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("remediation_plans.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rule_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("compliance_rules.id")),
        sa.Column("drift_event_id", postgresql.UUID(as_uuid=True)),  # no FK: drift_events is a hypertable, agent_id is part of its PK
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(20), nullable=False),  # ansible/shell/python/terraform
        sa.Column("rendered_body", sa.Text, nullable=False),
        sa.Column("rollback_body", sa.Text),
        sa.Column("sequence", sa.Integer, nullable=False, server_default="0"),
    )
    op.create_index("ix_remediation_actions_plan", "remediation_actions", ["remediation_plan_id"])
    op.create_index("ix_remediation_actions_agent", "remediation_actions", ["agent_id"])

    op.create_table(
        "remediation_jobs",
        sa.Column("remediation_plan_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("remediation_plans.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("jobs.id", ondelete="CASCADE"), primary_key=True),
    )


def downgrade() -> None:
    op.drop_table("remediation_jobs")
    op.drop_index("ix_remediation_actions_agent", table_name="remediation_actions")
    op.drop_index("ix_remediation_actions_plan", table_name="remediation_actions")
    op.drop_table("remediation_actions")
    op.drop_index("ix_remediation_plans_status", table_name="remediation_plans")
    op.drop_table("remediation_plans")
    op.drop_table("maintenance_windows")
