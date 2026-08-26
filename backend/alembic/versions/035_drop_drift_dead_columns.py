"""drop dead drift_events columns — Enterprise Compliance plan U1 (R11).

`changed_by_user` and `root_cause` were created by migration 017 but never
written or read anywhere in backend/frontend/agent/compliance services
(repo-wide reference sweep verified: zero consumers outside the model
definition itself). Incident root-cause is a different concept stored on
the incidents table (root_cause_signal_id) and is untouched.

Safe per plan §KTD10: ALTER TABLE ... DROP COLUMN IF EXISTS on a hypertable;
no reader/writer to break, downgrade recreates both columns.

Revision ID: 035
Create Date: 2026-08-26
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "035"
down_revision = "034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE drift_events DROP COLUMN IF EXISTS changed_by_user")
    op.execute("ALTER TABLE drift_events DROP COLUMN IF EXISTS root_cause")


def downgrade() -> None:
    op.add_column("drift_events", sa.Column("changed_by_user", sa.String(255), nullable=True))
    op.add_column("drift_events", sa.Column("root_cause", postgresql.JSONB, nullable=True))
