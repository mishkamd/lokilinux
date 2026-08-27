"""policy_sets.remediation — Enterprise Compliance plan U7/KTD8.

{mode: MONITOR|ASSISTED|AUTOMATIC, allowed: [domains], forbidden: [domains]},
nullable, no backfill: NULL means ASSISTED (current behavior — every
existing policy set is unaffected by this migration).

Revision ID: 041
Create Date: 2026-08-27
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "041"
down_revision = "040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("policy_sets", sa.Column("remediation", postgresql.JSONB, nullable=True))


def downgrade() -> None:
    op.drop_column("policy_sets", "remediation")
