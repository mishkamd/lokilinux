"""Approval claims table — signed approvals bound to one job execution.

Revision ID: 030
Create Date: 2026-08-25
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "030"
down_revision = "029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "approval_claims",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("job_id", UUID(as_uuid=True),
                  sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("approver_id", sa.String(255), nullable=True),
        sa.Column("claim_json", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("approval_claims")
