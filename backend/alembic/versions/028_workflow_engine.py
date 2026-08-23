"""Add Workflow Engine tables.

Revision ID: 028
Create Date: 2026-08-22

A workflow is a DAG of steps stored two ways: workflow_versions.yaml_source
(authoritative for humans and Git) and .graph (parsed+validated, what the
engine reads — see lokilinux/services/workflow_compiler.py). Versions are
immutable once PUBLISHED, mirroring BaselineVersion (migration 015).

Execution never talks to agents directly — each step becomes a Job via the
existing JobService (create_table order below keeps that containment: no
new dispatch path, jobs.workflow_step_run_id is the only new touch on the
Job table, exactly like jobs.policy_id already links to Policy).

workflows <-> workflow_versions is a two-way reference (a workflow points at
its current published version; a version points back at its workflow), so
workflows.current_version_id is added via op.add_column after
workflow_versions exists rather than inline in create_table.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "028"
down_revision = "027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workflows",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(80), nullable=False, unique=True),
        sa.Column("description", sa.Text),
        sa.Column("is_enabled", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("current_version_id", postgresql.UUID(as_uuid=True)),  # FK added below
        sa.Column("trigger_type", sa.String(30), nullable=False, server_default="MANUAL"),
        sa.Column("cron_expr", sa.String(100)),
        sa.Column("next_run_at", sa.DateTime(timezone=True)),
        sa.Column("last_run_at", sa.DateTime(timezone=True)),
        sa.Column("priority", sa.Integer, nullable=False, server_default="100"),
        sa.Column("severity", sa.String(20)),
        sa.Column("tags", postgresql.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("migrated_from_policy_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("policies.id")),
        sa.Column("created_by", postgresql.UUID(as_uuid=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "workflow_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("workflow_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("yaml_source", sa.Text, nullable=False),
        sa.Column("graph", postgresql.JSONB, nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="DRAFT"),
        sa.Column("change_summary", sa.Text),
        sa.Column("created_by", postgresql.UUID(as_uuid=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("workflow_id", "version", name="uq_workflow_versions_workflow_version"),
    )
    op.create_index("ix_workflow_versions_workflow", "workflow_versions", ["workflow_id"])

    # SET NULL, not the default NO ACTION: deleting a workflow cascades onto
    # its own workflow_versions rows (below), one of which this same
    # workflows row may point back at via current_version_id — without
    # SET NULL that back-reference blocks its own row's delete.
    op.create_foreign_key(
        "fk_workflows_current_version_id", "workflows", "workflow_versions",
        ["current_version_id"], ["id"], ondelete="SET NULL",
    )

    op.create_table(
        "workflow_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("workflow_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False),
        sa.Column("workflow_version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workflow_versions.id"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column("trigger_type", sa.String(20), nullable=False),
        sa.Column("triggered_by", postgresql.UUID(as_uuid=True)),
        sa.Column("targets", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("vars", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("is_dry_run", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("error", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_workflow_runs_workflow", "workflow_runs", ["workflow_id"])
    op.create_index("ix_workflow_runs_status", "workflow_runs", ["status"])

    op.create_table(
        "workflow_step_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workflow_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("step_id", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column("attempt", sa.Integer, nullable=False, server_default="1"),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("jobs.id", ondelete="SET NULL")),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("output", postgresql.JSONB),
        sa.Column("error", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("run_id", "step_id", "attempt", name="uq_workflow_step_runs_run_step_attempt"),
    )
    op.create_index("ix_workflow_step_runs_run", "workflow_step_runs", ["run_id"])

    op.create_table(
        "workflow_audit",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("workflow_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False),
        sa.Column("changed_by", postgresql.UUID(as_uuid=True)),
        sa.Column("change_type", sa.String(50), nullable=False),
        sa.Column("old_value", postgresql.JSONB),
        sa.Column("new_value", postgresql.JSONB),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_workflow_audit_workflow", "workflow_audit", ["workflow_id"])
    op.create_index("ix_workflow_audit_changed_at", "workflow_audit", ["changed_at"])

    # No reverse column on jobs (no jobs.workflow_step_run_id): unlike
    # RemediationPlan, the engine (workers/workflow_runner.py, Phase 6) is a
    # tick-based poller that already holds each RUNNING run's step_runs and
    # reads workflow_step_runs.job_id to check status — it never needs to
    # start from a Job row and look backwards. A bidirectional FK here would
    # just be two copies of the same fact that could drift out of sync.


def downgrade() -> None:
    op.drop_index("ix_workflow_audit_changed_at", table_name="workflow_audit")
    op.drop_index("ix_workflow_audit_workflow", table_name="workflow_audit")
    op.drop_table("workflow_audit")

    op.drop_index("ix_workflow_step_runs_run", table_name="workflow_step_runs")
    op.drop_table("workflow_step_runs")

    op.drop_index("ix_workflow_runs_status", table_name="workflow_runs")
    op.drop_index("ix_workflow_runs_workflow", table_name="workflow_runs")
    op.drop_table("workflow_runs")

    op.drop_constraint("fk_workflows_current_version_id", "workflows", type_="foreignkey")
    op.drop_index("ix_workflow_versions_workflow", table_name="workflow_versions")
    op.drop_table("workflow_versions")

    op.drop_table("workflows")
