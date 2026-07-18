"""Add total/used byte columns + swap to agent_health.

Revision ID: 013
Create Date: 2026-07-17

agent_health previously stored only cpu/memory/disk usage percentages.
The agent already collects (and now sends) absolute total/used bytes for
memory and disk, plus swap (not collected before at all). This adds the
columns needed to show "X used of Y total" on the server metrics cards
instead of just a bare percentage.
"""

import sqlalchemy as sa
from alembic import op

revision = "013"
down_revision = "012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agent_health", sa.Column("cpu_count", sa.Integer))
    op.add_column("agent_health", sa.Column("memory_total_bytes", sa.BigInteger))
    op.add_column("agent_health", sa.Column("memory_used_bytes", sa.BigInteger))
    op.add_column("agent_health", sa.Column("disk_total_bytes", sa.BigInteger))
    op.add_column("agent_health", sa.Column("disk_used_bytes", sa.BigInteger))
    op.add_column("agent_health", sa.Column("swap_usage", sa.Float))
    op.add_column("agent_health", sa.Column("swap_total_bytes", sa.BigInteger))
    op.add_column("agent_health", sa.Column("swap_used_bytes", sa.BigInteger))


def downgrade() -> None:
    op.drop_column("agent_health", "swap_used_bytes")
    op.drop_column("agent_health", "swap_total_bytes")
    op.drop_column("agent_health", "swap_usage")
    op.drop_column("agent_health", "disk_used_bytes")
    op.drop_column("agent_health", "disk_total_bytes")
    op.drop_column("agent_health", "memory_used_bytes")
    op.drop_column("agent_health", "memory_total_bytes")
    op.drop_column("agent_health", "cpu_count")
