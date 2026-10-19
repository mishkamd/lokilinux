"""compliance_reports.storage_object_id — dual-read migration to object storage.

New reports (services/report_service.py) are written to storage_objects and
this column set instead of the legacy body BYTEA column. body stays nullable
and populated for old rows — routers/compliance/reports.py:download_report
reads storage_object_id first, falling back to body. No backfill: dropping
body is a later migration once retention has expired (see the Object
Storage plan's Phase 4 notes).

Revision ID: 046
Create Date: 2026-09-03
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "046"
down_revision = "045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "compliance_reports",
        sa.Column(
            "storage_object_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("storage_objects.id"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("compliance_reports", "storage_object_id")
