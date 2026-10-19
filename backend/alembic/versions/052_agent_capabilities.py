"""agents.capabilities — native job types an agent reports on heartbeat (ROADMAP R5).

Nullable with no backfill: an agent that has never reported has NULL, and
dispatch treats that as "no native support" (the shell fallback path).

Revision ID: 052
Create Date: 2026-10-14
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "052"
down_revision = "051"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agents", sa.Column("capabilities", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("agents", "capabilities")
