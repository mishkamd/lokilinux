"""drop the abandoned update-management tables (MIS-169).

Migration 002 created update_policies / update_jobs / update_job_results for a
package-update management feature that was never completed: no SQLAlchemy model,
no service, no router, no frontend — the tables were write-only dead weight in
every deployment. Live schema check: 0 rows in all three.

The dsc_* tables are NOT touched here — they hold 8.2M frozen rows from a
feature whose code was lost with a deleted branch (recoverable from
recovery/dsc-2026-08-24). Dropping them is a separate, explicit decision.

Revision ID: 062
Create Date: 2026-10-17
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "062"
down_revision = "061"
branch_labels = None
depends_on = None

# Child first: update_job_results.job_id is an FK to update_jobs.id.
_TABLES = ("update_job_results", "update_jobs", "update_policies")


def upgrade() -> None:
    for table in _TABLES:
        op.drop_table(table)


def downgrade() -> None:
    # Recreate the exact shape migration 002 built (empty tables).
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
    op.create_index("ix_update_job_scope", "update_jobs", ["scope"])
    op.create_index("ix_update_job_status", "update_jobs", ["status"])
    op.create_index("ix_update_result_job_id", "update_job_results", ["job_id"])
    op.create_index("ix_update_result_agent_id", "update_job_results", ["agent_id"])
