"""Drop agents.scope column and its index.

Revision ID: 008
Create Date: 2026-07-03

Scope was dead: never editable in the UI (always "default"), and no
job/policy targeting code actually read it. Removed entirely.
"""

import sqlalchemy as sa
from alembic import op

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("ix_agents_scope", table_name="agents")
    op.drop_column("agents", "scope")


def downgrade() -> None:
    op.add_column("agents", sa.Column("scope", sa.String(50), nullable=False, server_default="default"))
    op.create_index("ix_agents_scope", "agents", ["scope"])
