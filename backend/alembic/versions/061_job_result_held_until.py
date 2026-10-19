"""job_results.held_until: hold window for a job held back by an envelope signing failure (MIS-29).

A held job stays PENDING, so without a window get_pending_jobs returns it again on every
heartbeat and it fills the pending window. Nullable, no backfill: NULL means not held.

Revision ID: 061
Create Date: 2026-10-16
"""

import sqlalchemy as sa

from alembic import op

revision = "061"
down_revision = "060"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("job_results", sa.Column("held_until", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("job_results", "held_until")
