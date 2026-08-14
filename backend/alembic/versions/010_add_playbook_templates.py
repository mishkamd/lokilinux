"""Add playbook_templates table (AWX "Job Template" equivalent).

Revision ID: 010
Create Date: 2026-07-04

A template saves (playbook + default agents + default extra_vars) as a
reusable, one-click launch config. References playbooks.id rather than
duplicating content.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "playbook_templates",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("playbook_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("playbooks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.String),
        sa.Column("agent_ids", postgresql.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("extra_vars", postgresql.JSONB),
        sa.Column("created_by", postgresql.UUID(as_uuid=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_playbook_templates_playbook_id", "playbook_templates", ["playbook_id"])


def downgrade() -> None:
    op.drop_index("ix_playbook_templates_playbook_id", table_name="playbook_templates")
    op.drop_table("playbook_templates")
