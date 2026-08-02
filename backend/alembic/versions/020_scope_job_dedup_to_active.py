"""Scope the jobs.dedup_key unique index to active jobs only.

Revision ID: 020
Create Date: 2026-07-30

001_initial_schema created uq_jobs_dedup_key as a partial unique index whose
only predicate was `dedup_key IS NOT NULL`. That made the constraint strictly
harsher than the application ever intended: JobService.create_job's own
duplicate check (job_service.py) already limits itself to *active* statuses,
so once any job existed with a given (job_type, target_servers, parameters)
triple, the app-level check would correctly let a retry through after the old
job died — and then the DB index would reject it with a UniqueViolation that
nothing catches, surfacing as a 500 instead of a clean 409.

Observed live: a PACKAGE_UPDATE job for "update everything" always hashes to
the same dedup_key (parameters is null), so after the first one reached a
terminal state the feature was permanently unusable from the UI.

Aligning the index predicate with the app's definition of "active" makes the
two agree; the index still prevents genuine concurrent duplicates.
"""

import sqlalchemy as sa
from alembic import op

revision = "020"
down_revision = "019"
branch_labels = None
depends_on = None

_ACTIVE_STATUSES = "'QUEUED', 'SCHEDULED', 'PENDING', 'RUNNING'"


def upgrade() -> None:
    op.drop_index("uq_jobs_dedup_key", table_name="jobs")
    op.create_index(
        "uq_jobs_dedup_key",
        "jobs",
        ["dedup_key"],
        unique=True,
        postgresql_where=sa.text(
            f"dedup_key IS NOT NULL AND status IN ({_ACTIVE_STATUSES})"
        ),
    )


def downgrade() -> None:
    op.drop_index("uq_jobs_dedup_key", table_name="jobs")
    op.create_index(
        "uq_jobs_dedup_key",
        "jobs",
        ["dedup_key"],
        unique=True,
        postgresql_where=sa.text("dedup_key IS NOT NULL"),
    )
