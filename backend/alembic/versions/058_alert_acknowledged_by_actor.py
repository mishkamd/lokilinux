"""alerts.acknowledged_by_actor: the acknowledger's raw auth id (MIS-8).

acknowledged_by is a UUID column, and Better Auth ids are nanoids that never parse
as UUID. The acknowledgement used to skip the actor entirely for those users, so
nothing recorded who acknowledged the alert. The raw id is kept beside it. Nullable,
no backfill: alerts acknowledged before this migration keep the UUID column only.

Revision ID: 058
Create Date: 2026-10-16
"""

import sqlalchemy as sa

from alembic import op

revision = "058"
down_revision = "057"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("alerts", sa.Column("acknowledged_by_actor", sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column("alerts", "acknowledged_by_actor")
