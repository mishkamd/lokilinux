"""Add playbooks table for the Ansible automation plugin.

Revision ID: 009
Create Date: 2026-07-04

Ansible plugin stores playbook YAML directly in DB (content column),
mirroring how Policy.rules is stored as JSONB — no separate file storage
layer exists in this codebase, so this follows the established pattern.
No separate audit table: reuses the generic audit_logs table like other
entities.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "playbooks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.String),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("is_enabled", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("generated_by", sa.String(20)),
        sa.Column("default_extra_vars", postgresql.JSONB),
        sa.Column("created_by", postgresql.UUID(as_uuid=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_playbooks_is_enabled", "playbooks", ["is_enabled"])

    # Seed the Plugin row so "Ansible" shows up in /plugins to be installed
    # and enabled/disabled — playbook routes gate on plugins.is_enabled.
    op.execute(
        """
        INSERT INTO plugins (name, display_name, version, description, author,
                              plugin_type, manifest, is_enabled, is_installed,
                              installation_status)
        VALUES (
            'ansible-automation',
            'Ansible',
            '1.0.0',
            'Run Ansible playbooks against selected fleet agents (local execution, no SSH).',
            'LokiLinux',
            'control-plane',
            '{"name": "ansible-automation", "version": "1.0.0", "description": "Ansible automation engine", "author": "LokiLinux", "entrypoint": "playbooks", "permissions": ["job:create", "job:approve"]}'::jsonb,
            false,
            true,
            'INSTALLED'
        )
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM plugins WHERE name = 'ansible-automation'")
    op.drop_index("ix_playbooks_is_enabled", table_name="playbooks")
    op.drop_table("playbooks")
