"""Add agents.fqdn, agents.system_users, agents.recent_logs.

Revision ID: 003
Create Date: 2026-07-01

Reported by heartbeat: fqdn (resolved from system_status), system_users
(local OS accounts UID >= 1000), recent_logs (last N agent log lines).
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agents", sa.Column("fqdn", sa.String(255)))
    op.add_column("agents", sa.Column("system_users", postgresql.JSONB))
    op.add_column("agents", sa.Column("recent_logs", postgresql.JSONB))


def downgrade() -> None:
    op.drop_column("agents", "recent_logs")
    op.drop_column("agents", "system_users")
    op.drop_column("agents", "fqdn")
