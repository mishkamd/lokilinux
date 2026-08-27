"""compliance_frameworks metadata columns — Enterprise Compliance plan U8/KTD6.

Optional publisher/description/status, nullable, no backfill — UI shows
them when present, falls back to just key/name otherwise. Purely additive.

Revision ID: 040
Create Date: 2026-08-27
"""

import sqlalchemy as sa
from alembic import op

revision = "040"
down_revision = "039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("compliance_frameworks", sa.Column("publisher", sa.String(255), nullable=True))
    op.add_column("compliance_frameworks", sa.Column("description", sa.Text(), nullable=True))
    op.add_column("compliance_frameworks", sa.Column("status", sa.String(20), nullable=True))


def downgrade() -> None:
    op.drop_column("compliance_frameworks", "status")
    op.drop_column("compliance_frameworks", "description")
    op.drop_column("compliance_frameworks", "publisher")
