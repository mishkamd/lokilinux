"""agents.agent_group_id — agent-policy-modernization plan Phase 3/4.

Fixes a dead reference: agent_policies.py's GROUP-scope deploy resolution
already queries Agent.agent_group_id (previously named
Agent.enrollment_group_id in code that never matched any real column —
AttributeError waiting to happen the first time GROUP scope was exercised).
Also the landing spot for enrollment tokens' agent_group binding once
agent_install.py's enrollment cutover (same change) stamps it on register.

Revision ID: 043
Create Date: 2026-08-28
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "043"
down_revision = "042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agents",
        sa.Column(
            "agent_group_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_groups.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("agents", "agent_group_id")
