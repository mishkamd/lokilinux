"""Add agents.last_packages_checksum.

Revision ID: 004
Create Date: 2026-07-03

Lets update_heartbeat skip the package upsert entirely when the agent's
reported checksum matches what was already synced — the agent already
computes this checksum every heartbeat but the backend never used it.
"""

import sqlalchemy as sa

from alembic import op

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agents", sa.Column("last_packages_checksum", sa.String(64)))


def downgrade() -> None:
    op.drop_column("agents", "last_packages_checksum")
