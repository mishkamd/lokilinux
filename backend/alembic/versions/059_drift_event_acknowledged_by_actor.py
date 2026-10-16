"""drift_events.acknowledged_by_actor: the acknowledger's raw auth id (MIS-8 family).

acknowledged_by is a UUID column, so a nanoid acknowledger was recorded as NULL.
The raw id is kept beside it. Nullable, no backfill; drift_events is a hypertable,
and a nullable column can be added to it directly.

Revision ID: 059
Create Date: 2026-10-16
"""

import sqlalchemy as sa

from alembic import op

revision = "059"
down_revision = "058"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("drift_events", sa.Column("acknowledged_by_actor", sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column("drift_events", "acknowledged_by_actor")
