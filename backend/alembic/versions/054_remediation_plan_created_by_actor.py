"""remediation_plans.created_by_actor: the creator's raw auth id (MIS-29).

created_by is a UUID column and Better Auth ids are nanoids that never parse as
UUID, so a nanoid creator was stored as NULL and the no-self-approval check could
not match them. The raw id is kept beside it. Nullable, no backfill: plans created
before this migration keep the UUID check only.

Revision ID: 054
Create Date: 2026-10-16
"""

import sqlalchemy as sa

from alembic import op

revision = "054"
down_revision = "053"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("remediation_plans", sa.Column("created_by_actor", sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column("remediation_plans", "created_by_actor")
