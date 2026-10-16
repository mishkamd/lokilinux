"""workflow_versions — dual-read migration to object storage.

New workflow versions write yaml_source to storage_objects instead of the
inline column (Object Storage plan). yaml_source is relaxed to nullable so
old rows keep reading from it; content_object_id is the new pointer.
content_hash stays a plain column either way — it's computed from the YAML
text regardless of where the text lives, and is what optimistic concurrency
and PUBLISHED immutability actually key off.

No backfill — old rows keep working via the legacy column exactly as
compliance_reports.body (046) and playbooks.content/ansible_roles.files
(047) do.

Revision ID: 048
Create Date: 2026-09-03
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "048"
down_revision = "047"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("workflow_versions", "yaml_source", existing_type=sa.Text(), nullable=True)
    op.add_column(
        "workflow_versions",
        sa.Column(
            "content_object_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("storage_objects.id"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("workflow_versions", "content_object_id")
    op.alter_column("workflow_versions", "yaml_source", existing_type=sa.Text(), nullable=False)
