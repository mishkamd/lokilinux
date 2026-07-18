"""Add agents.disks / network_interfaces / block_devices.

Revision ID: 005
Create Date: 2026-07-03

Full hardware snapshot reported every heartbeat (df/ip-a/lsblk-style data) —
overwritten wholesale each heartbeat, no history kept. Mirrors the existing
system_users/recent_logs JSONB columns.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agents", sa.Column("disks", postgresql.JSONB))
    op.add_column("agents", sa.Column("network_interfaces", postgresql.JSONB))
    op.add_column("agents", sa.Column("block_devices", postgresql.JSONB))


def downgrade() -> None:
    op.drop_column("agents", "block_devices")
    op.drop_column("agents", "network_interfaces")
    op.drop_column("agents", "disks")
