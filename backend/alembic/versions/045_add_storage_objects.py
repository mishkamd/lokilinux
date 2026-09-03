"""storage_objects — centralized object storage metadata (Object Storage plan).

Creates only the metadata table — no data migration, no S3 write. Keeps
lokilinux-migrate idempotent and independent of RustFS being reachable.
Existing blob columns (compliance_reports.body, etc.) are migrated to
reference this table in later migrations via a nullable storage_object_id
FK, with dual-read fallback — this migration does not touch them.

Revision ID: 045
Create Date: 2026-09-03
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "045"
down_revision = "044"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "storage_objects",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(255), nullable=False),
        sa.Column("size_bytes", sa.BigInteger, nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("storage_provider", sa.String(20), nullable=False, server_default="s3"),
        sa.Column("bucket", sa.String(255), nullable=False),
        sa.Column("object_key", sa.String(1000), nullable=False),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("category", sa.String(100), nullable=False),
        sa.Column("metadata", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(20), nullable=False, server_default="AVAILABLE"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_unique_constraint("uq_storage_objects_object_key", "storage_objects", ["object_key"])
    op.create_index("ix_storage_objects_sha256", "storage_objects", ["sha256"])
    op.create_index(
        "ix_storage_objects_category_created_at",
        "storage_objects",
        ["category", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_storage_objects_category_created_at", table_name="storage_objects")
    op.drop_index("ix_storage_objects_sha256", table_name="storage_objects")
    op.drop_constraint("uq_storage_objects_object_key", "storage_objects", type_="unique")
    op.drop_table("storage_objects")
