"""Add rollback_body to remediation_templates.

Revision ID: 026
Revises: 025

remediation_templates (migration 016) only ever stored the apply body — a
RemediationAction (the per-plan-instance row) has its own rollback_body,
but the catalog-level template had nowhere to carry a paired rollback for
curated content to populate (F10: SSH-001 and friends define both).
Nullable — plenty of remediations (e.g. removing an unrestricted sudoers
line) are intentionally not auto-reversible.
"""

import sqlalchemy as sa

from alembic import op

revision = "026"
down_revision = "025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("remediation_templates", sa.Column("rollback_body", sa.Text))


def downgrade() -> None:
    op.drop_column("remediation_templates", "rollback_body")
