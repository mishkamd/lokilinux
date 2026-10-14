"""agents: per-agent snapshot HMAC keys, current and previous (P1r-3.1).

Keys live in the database, as decided in docs/security/SNAPSHOT_HMAC.md. The
previous key is kept so snapshots signed just before a rotation still verify.
Nullable with no backfill: an agent gets its first key on its next heartbeat.

Revision ID: 053
Create Date: 2026-10-14
"""

import sqlalchemy as sa

from alembic import op

revision = "053"
down_revision = "052"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agents", sa.Column("snapshot_hmac_key", sa.Text(), nullable=True))
    op.add_column("agents", sa.Column("snapshot_hmac_key_id", sa.Integer(), nullable=True))
    op.add_column("agents", sa.Column("snapshot_hmac_prev_key", sa.Text(), nullable=True))
    op.add_column("agents", sa.Column("snapshot_hmac_prev_key_id", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("agents", "snapshot_hmac_prev_key_id")
    op.drop_column("agents", "snapshot_hmac_prev_key")
    op.drop_column("agents", "snapshot_hmac_key_id")
    op.drop_column("agents", "snapshot_hmac_key")
