"""workflow_versions.published_by_actor: the publisher's raw auth id (MIS-29 follow-up).

published_by is a UUID column, and Better Auth ids are nanoids that never parse as
UUID, so a nanoid publisher was stored as NULL and the no-self-approval check in
approve_step could not match them. The raw id is kept beside it. Nullable, no
backfill: versions published before this migration keep the UUID check only.

Revision ID: 056
Create Date: 2026-10-16
"""

import sqlalchemy as sa

from alembic import op

revision = "056"
down_revision = "055"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "workflow_versions", sa.Column("published_by_actor", sa.String(255), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("workflow_versions", "published_by_actor")
