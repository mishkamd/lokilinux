"""workflow_versions.published_by — who published a version (Phase 11, no-self-approval).

Nullable with no backfill: versions published before this migration have no
recorded publisher, so the approval check skips them. That matches how the
other dual-read columns in this codebase are handled (see 046-048).

Revision ID: 050
Create Date: 2026-10-14
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "050"
down_revision = "049"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "workflow_versions",
        sa.Column("published_by", postgresql.UUID(as_uuid=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("workflow_versions", "published_by")
