"""Add Reporting Engine table (Compliance module, Phase 5).

Revision ID: 019
Create Date: 2026-07-30

Per docs/compliance/01-DATA-MODEL.md §8 and 05-API.md §7. `body` is a
deviation from the doc's literal spec (`artifact_uri VARCHAR` pointing at
external object storage) — this deployment has no S3/minio, and every
other content-bearing table in this module (inventory_blobs,
remediation_templates) already stores bodies directly in Postgres rather
than inventing new infra. `artifact_uri` is kept (nullable) as the
documented column name, populated with this API's own download path once
COMPLETED, not an external URI.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "019"
down_revision = "018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "compliance_reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("report_type", sa.String(30), nullable=False),  # FLEET_SUMMARY/POLICY_SET/DATACENTER/CUSTOM
        sa.Column("format", sa.String(10), nullable=False),  # PDF/CSV/XLSX/JSON
        sa.Column("params", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),  # PENDING/GENERATING/COMPLETED/FAILED
        sa.Column("artifact_uri", sa.String(1000)),
        sa.Column("body", postgresql.BYTEA),
        sa.Column("error_message", sa.Text),
        sa.Column("generated_by", postgresql.UUID(as_uuid=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_compliance_reports_status", "compliance_reports", ["status"])


def downgrade() -> None:
    op.drop_index("ix_compliance_reports_status", table_name="compliance_reports")
    op.drop_table("compliance_reports")
