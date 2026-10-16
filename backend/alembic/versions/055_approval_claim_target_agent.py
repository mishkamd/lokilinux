"""approval_claims.target_agent_id: one signed claim per target agent (MIS-29 follow-up).

A multi-target job used to get one claim bound to its first target, so every other
agent rejected it (ClaimWrongTarget). Each claim now names its agent. Nullable with
no backfill: existing claims stay job-scoped and are served as before.

Revision ID: 055
Create Date: 2026-10-16
"""

import sqlalchemy as sa

from alembic import op

revision = "055"
down_revision = "054"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("approval_claims", sa.Column("target_agent_id", sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column("approval_claims", "target_agent_id")
