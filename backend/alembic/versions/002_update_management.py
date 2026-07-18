"""Add update management tables and fields.

Revision ID: 002
Create Date: 2026-06-27

Source: docs/LOKILINUX_AGENT_COMMUNICATION_UPDATES.md §IV.4.1
Deviations from source doc:
  - agents.scope and agents.cve_count already exist in 001 → skipped here
  - packages.is_security_update and packages.installed_date differ in name from
    001's is_security_update_available / installed_at — added as separate columns
    for the update-management feature layer
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── agents: new columns only (scope + cve_count already in 001) ──────────
    op.add_column("agents", sa.Column("cve_last_scan", sa.DateTime(timezone=True)))

    # ── packages: update-management-specific columns ──────────────────────────
    # 'source' is the update-manager's view of origin (distinct from 'repository')
    op.add_column("packages", sa.Column("source", sa.String(255)))
    # 'is_security_update' is the update-job flag (distinct from is_security_update_available)
    op.add_column("packages", sa.Column("is_security_update", sa.Boolean, server_default=sa.text("false")))
    # 'installed_date' stores the update-job timestamp (distinct from installed_at)
    op.add_column("packages", sa.Column("installed_date", sa.DateTime(timezone=True)))

    # ── repositories ─────────────────────────────────────────────────────────
    op.create_table(
        "repositories",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("type", sa.String(50)),          # apt / dnf / yum
        sa.Column("url", sa.String(512)),
        sa.Column("distribution", sa.String(100)),
        sa.Column("components", postgresql.JSONB, server_default=sa.text("'[]'::jsonb")),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("package_count", sa.Integer, server_default="0"),
        sa.Column("last_update", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_repo_agent_id", "repositories", ["agent_id"])

    # ── update_policies ───────────────────────────────────────────────────────
    op.create_table(
        "update_policies",
        sa.Column("id", sa.String(50), primary_key=True),
        sa.Column("scope", sa.String(50), nullable=False),
        sa.Column("security_only", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("include_minor", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("include_major", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("auto_update_enabled", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("update_strategy", sa.String(50)),  # immediate / staged / canary / maintenance_window / manual
        sa.Column("staging_wave_hours", sa.Integer, server_default="24"),
        sa.Column("canary_waves", postgresql.JSONB, server_default=sa.text("'[5,25,100]'::jsonb")),
        sa.Column("canary_wait_hours", sa.Integer, server_default="6"),
        sa.Column("maintenance_window", sa.String(100)),
        sa.Column("requires_approval", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("auto_reboot_if_required", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("reboot_wait_hours", sa.Integer, server_default="24"),
        sa.Column("notify_on_completion", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("notification_channels", postgresql.JSONB, server_default=sa.text("'[\"email\"]'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    # ── update_jobs ───────────────────────────────────────────────────────────
    op.create_table(
        "update_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("scope", sa.String(50), nullable=False),
        sa.Column("strategy", sa.String(50)),
        sa.Column("target_count", sa.Integer),
        sa.Column("completed_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("status", sa.String(50)),        # pending / running / completed / failed / rolled_back
        sa.Column("current_wave", sa.Integer, nullable=False, server_default="0"),
        sa.Column("total_waves", sa.Integer, nullable=False, server_default="1"),
        sa.Column("package_filter", sa.String(255)),
        sa.Column("security_only", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("changelog", postgresql.JSONB, server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_by", postgresql.UUID(as_uuid=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_update_job_scope", "update_jobs", ["scope"])
    op.create_index("ix_update_job_status", "update_jobs", ["status"])

    # ── update_job_results ────────────────────────────────────────────────────
    op.create_table(
        "update_job_results",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("update_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(50)),        # pending / running / completed / failed
        sa.Column("packages_updated", sa.Integer, nullable=False, server_default="0"),
        sa.Column("exit_code", sa.Integer),
        sa.Column("output", sa.Text),
        sa.Column("error_message", sa.Text),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_update_result_job_id", "update_job_results", ["job_id"])
    op.create_index("ix_update_result_agent_id", "update_job_results", ["agent_id"])


def downgrade() -> None:
    op.drop_table("update_job_results")
    op.drop_table("update_jobs")
    op.drop_table("update_policies")
    op.drop_table("repositories")
    op.drop_column("packages", "installed_date")
    op.drop_column("packages", "is_security_update")
    op.drop_column("packages", "source")
    op.drop_column("agents", "cve_last_scan")
