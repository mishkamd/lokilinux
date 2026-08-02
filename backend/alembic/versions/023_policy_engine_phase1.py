"""Policy Engine Phase 1: cron trigger, actions, execution config.

Revision ID: 023
Create Date: 2026-08-02

Extends the existing `policies` table rather than creating a new one — the
CRUD/audit machinery around it (router, PolicyAudit, PolicyWorker's cache
invalidation) is already correct, only the "what happens when" half was
missing. `rules` (the free-form JSONB blob nothing has ever read) is left
untouched — reserved for Phase 2 conditions, not repurposed here.

`actions` is a list, not a single object, even though Phase 1 only ever
executes the first entry — avoids a second migration when multi-step
orchestration lands later.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "023"
down_revision = "022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("policies", sa.Column("trigger_type", sa.String(30), nullable=False, server_default="MANUAL"))
    op.add_column("policies", sa.Column("cron_expr", sa.String(100)))
    op.add_column("policies", sa.Column("next_run_at", sa.DateTime(timezone=True)))
    op.add_column("policies", sa.Column("last_run_at", sa.DateTime(timezone=True)))
    op.add_column("policies", sa.Column("actions", postgresql.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")))
    op.add_column("policies", sa.Column("execution", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")))
    op.add_column("policies", sa.Column("severity", sa.String(20)))
    op.add_column("policies", sa.Column("tags", postgresql.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")))

    op.create_index("ix_policies_next_run_at", "policies", ["next_run_at"])

    # jobs.policy_id has existed since 001 (write-only until now — see
    # JobService.create_job and the "Executions" tab this powers) but was
    # never indexed since nothing ever queried by it.
    op.create_index("ix_jobs_policy_id", "jobs", ["policy_id"])


def downgrade() -> None:
    op.drop_index("ix_jobs_policy_id", table_name="jobs")
    op.drop_index("ix_policies_next_run_at", table_name="policies")
    op.drop_column("policies", "tags")
    op.drop_column("policies", "severity")
    op.drop_column("policies", "execution")
    op.drop_column("policies", "actions")
    op.drop_column("policies", "last_run_at")
    op.drop_column("policies", "next_run_at")
    op.drop_column("policies", "cron_expr")
    op.drop_column("policies", "trigger_type")
