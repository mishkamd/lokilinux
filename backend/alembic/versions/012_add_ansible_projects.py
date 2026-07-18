"""Add ansible_projects table and playbooks.project_id column.

Revision ID: 012
Create Date: 2026-07-05

Projects group playbooks (equivalent of a real Ansible tree's projects/<name>/).
project_id is nullable — ungrouped playbooks show as "Debug/Uncategorized"
in the UI, matching a real project's debug/ directory of loose playbooks.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "012"
down_revision = "011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ansible_projects",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(255), nullable=False, unique=True),
        sa.Column("description", sa.String),
        sa.Column("default_agent_ids", postgresql.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_by", postgresql.UUID(as_uuid=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.add_column(
        "playbooks",
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("ansible_projects.id", ondelete="SET NULL"), nullable=True),
    )
    op.create_index("ix_playbooks_project_id", "playbooks", ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_playbooks_project_id", table_name="playbooks")
    op.drop_column("playbooks", "project_id")
    op.drop_table("ansible_projects")
