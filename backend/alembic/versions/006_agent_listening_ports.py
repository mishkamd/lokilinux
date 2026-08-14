"""Add agents.listening_ports.

Revision ID: 006
Create Date: 2026-07-03

Full listening-socket snapshot (ss -tulpn-style) reported every heartbeat —
overwritten wholesale each heartbeat, no history kept. Mirrors 005's
disks/network_interfaces/block_devices JSONB columns.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agents", sa.Column("listening_ports", postgresql.JSONB))


def downgrade() -> None:
    op.drop_column("agents", "listening_ports")
