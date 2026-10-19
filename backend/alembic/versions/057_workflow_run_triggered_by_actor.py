"""workflow_runs.triggered_by_actor: the trigger's raw auth id (MIS-29 follow-up).

triggered_by is a UUID column, so a nanoid user who started a run was stored as
NULL and the trigger check in approve_step could not match them. The raw id is
kept beside it. Nullable, no backfill: runs started before this migration keep
the UUID check only.

Revision ID: 057
Create Date: 2026-10-16
"""

import sqlalchemy as sa

from alembic import op

revision = "057"
down_revision = "056"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("workflow_runs", sa.Column("triggered_by_actor", sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column("workflow_runs", "triggered_by_actor")
