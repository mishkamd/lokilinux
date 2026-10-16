"""rule_evaluations.acknowledged_by_actor: the acknowledger's raw auth id (MIS-8 family).

Same gap as drift_events: a nanoid acknowledger of a compliance finding was recorded
as NULL in acknowledged_by. The raw id is kept beside it. Nullable, no backfill;
rule_evaluations is a hypertable, and a nullable column can be added to it directly.

Revision ID: 060
Create Date: 2026-10-16
"""

import sqlalchemy as sa

from alembic import op

revision = "060"
down_revision = "059"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "rule_evaluations", sa.Column("acknowledged_by_actor", sa.String(255), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("rule_evaluations", "acknowledged_by_actor")
