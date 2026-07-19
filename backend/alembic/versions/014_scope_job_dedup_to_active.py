"""Scope jobs.dedup_key uniqueness to active (non-terminal) jobs only.

Revision ID: 014
Create Date: 2026-07-19

The original partial unique index only excluded NULL dedup_key, not
status — so once any job (even later CANCELLED/COMPLETED/FAILED/TIMEOUT)
existed with a given dedup_key, no job with that same
(job_type, target_servers, parameters) combination could ever be created
again. JobService.create_job's own duplicate check only looks at active
statuses, so the DB constraint was stricter than the application ever
intended — every retry after a cancel/timeout hit an unhandled
IntegrityError -> 500 instead of the graceful 409 the app already has
logic for.
"""

import sqlalchemy as sa
from alembic import op

revision = "014"
down_revision = "013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("uq_jobs_dedup_key", table_name="jobs")
    op.create_index(
        "uq_jobs_dedup_key", "jobs", ["dedup_key"],
        unique=True,
        postgresql_where=sa.text(
            "dedup_key IS NOT NULL AND status IN "
            "('QUEUED', 'SCHEDULED', 'PENDING', 'RUNNING')"
        ),
    )


def downgrade() -> None:
    op.drop_index("uq_jobs_dedup_key", table_name="jobs")
    op.create_index(
        "uq_jobs_dedup_key", "jobs", ["dedup_key"],
        unique=True,
        postgresql_where=sa.text("dedup_key IS NOT NULL"),
    )
