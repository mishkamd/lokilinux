"""Add ansible_roles table and playbooks.role_ids column.

Revision ID: 011
Create Date: 2026-07-05

Roles are stored as JSONB path→content maps (same in-DB pattern as
playbook content). playbooks.role_ids lists which roles a playbook uses;
they are snapshotted into Job.parameters at execution time.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "011"
down_revision = "010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ansible_roles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(255), nullable=False, unique=True),
        sa.Column("description", sa.String),
        sa.Column("files", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("is_enabled", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("created_by", postgresql.UUID(as_uuid=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.add_column("playbooks", sa.Column("role_ids", postgresql.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")))


def downgrade() -> None:
    op.drop_column("playbooks", "role_ids")
    op.drop_table("ansible_roles")
