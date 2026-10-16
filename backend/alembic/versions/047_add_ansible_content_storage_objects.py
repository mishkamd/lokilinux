"""playbooks/ansible_roles — dual-read migration to object storage.

New playbooks/roles are written to storage_objects instead of the legacy
inline columns (Object Storage plan). Both `playbooks.content` and
`ansible_roles.files` are relaxed to nullable so old rows keep reading
from them; content_object_id is the new pointer. ansible_roles also gets
file_count (backfilled from the existing files map) so the roles list
endpoint can show a count without reading every role's content from S3.

No backfill of content into S3 — old rows keep working via the legacy
column exactly as compliance_reports.body does (migration 046).

Revision ID: 047
Create Date: 2026-09-03
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "047"
down_revision = "046"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("playbooks", "content", existing_type=sa.Text(), nullable=True)
    op.add_column(
        "playbooks",
        sa.Column(
            "content_object_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("storage_objects.id"),
            nullable=True,
        ),
    )

    op.alter_column("ansible_roles", "files", existing_type=postgresql.JSONB(), nullable=True)
    op.add_column(
        "ansible_roles",
        sa.Column(
            "content_object_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("storage_objects.id"),
            nullable=True,
        ),
    )
    op.add_column(
        "ansible_roles",
        sa.Column("file_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.execute(
        """
        UPDATE ansible_roles AS r
        SET file_count = (SELECT count(*) FROM jsonb_object_keys(r.files))
        WHERE r.files IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_column("ansible_roles", "file_count")
    op.drop_column("ansible_roles", "content_object_id")
    op.alter_column("ansible_roles", "files", existing_type=postgresql.JSONB(), nullable=False)

    op.drop_column("playbooks", "content_object_id")
    op.alter_column("playbooks", "content", existing_type=sa.Text(), nullable=False)
