"""Raw auth id of the creator on approval-gated jobs, baselines and exceptions (MIS-179).

created_by / requested_by are UUID and NULL for nanoid users, so the four-eyes check
could not see them. The raw id sits beside them, as remediation_plans.created_by_actor
does. Nullable, no backfill: older rows keep the UUID-only check.

Revision ID: 066
Create Date: 2026-10-26
"""

import sqlalchemy as sa

from alembic import op

revision = "066"
down_revision = "065"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("created_by_actor", sa.String(255), nullable=True))
    op.add_column("baseline_versions", sa.Column("created_by_actor", sa.String(255), nullable=True))
    op.add_column(
        "compliance_exceptions", sa.Column("requested_by_actor", sa.String(255), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("compliance_exceptions", "requested_by_actor")
    op.drop_column("baseline_versions", "created_by_actor")
    op.drop_column("jobs", "created_by_actor")
