"""Drop agents.cve_count — denormalized, never written.

Revision ID: 029
Create Date: 2026-08-23

Confirmed live: every row was 0 regardless of real vulnerability count
(agent_service._sync_vulnerabilities upserts agent_vulnerabilities but
never touched this column). routers/servers.py now computes the open-CVE
count per response from agent_vulnerabilities directly (Partea IV of the
workflow migration plan), so the column has no reader left either.
"""

import sqlalchemy as sa
from alembic import op

revision = "029"
down_revision = "028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("agents", "cve_count")


def downgrade() -> None:
    op.add_column("agents", sa.Column("cve_count", sa.Integer(), nullable=False, server_default="0"))
