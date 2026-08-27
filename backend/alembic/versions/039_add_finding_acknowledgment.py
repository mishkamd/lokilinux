"""rule_evaluations acknowledgment columns — Enterprise Compliance plan U4.

Additive, nullable — acknowledge is a lifecycle annotation on the finding's
row, same shape as drift_events.acknowledged_by/acknowledged_at (migration
017). No backfill: existing evaluations are simply unacknowledged.

Revision ID: 039
Create Date: 2026-08-27
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "039"
down_revision = "038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "rule_evaluations",
        sa.Column("acknowledged_by", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "rule_evaluations",
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("rule_evaluations", "acknowledged_at")
    op.drop_column("rule_evaluations", "acknowledged_by")
