"""fim_scopes — operator-configured file-integrity watch/ignore scope.

Gives the platform a real control-plane channel for what the agent's FIM
collector scans, replacing "only the local agent.yaml on each host, which
both installers write empty" (agent/internal/compliance/file_integrity_collector.go,
scripts/install-agent.sh). GLOBAL row is the fleet default; an AGENT row
overrides it for one server. Delivered to agents as a signed document over
the heartbeat (services/fim_scope_service.py, MIN_AGENT_VERSION_FIM_SCOPES) —
this table is not file_integrity_ignores (migration 017), which is a
GLOBAL-only post-ingest filter with no writer and no delivery to agents.

Seeds one GLOBAL row of watch_paths=['/etc'] so the UI reflects the agent's
real compiled-in default from day one instead of an empty list.

Revision ID: 044
Create Date: 2026-09-02
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "044"
down_revision = "043"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fim_scopes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("scope_type", sa.String(16), nullable=False),  # GLOBAL | AGENT
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=True),
        sa.Column("watch_paths", postgresql.JSONB, nullable=False),
        sa.Column("ignore_paths", postgresql.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True)),
    )
    op.create_index(
        "ux_fim_scopes_global", "fim_scopes", ["scope_type"],
        unique=True, postgresql_where=sa.text("scope_type = 'GLOBAL'"),
    )
    op.create_index(
        "ux_fim_scopes_agent", "fim_scopes", ["agent_id"],
        unique=True, postgresql_where=sa.text("scope_type = 'AGENT'"),
    )

    op.execute(
        """
        INSERT INTO fim_scopes (scope_type, watch_paths, ignore_paths)
        VALUES ('GLOBAL', '["/etc"]'::jsonb, '[]'::jsonb)
        """
    )


def downgrade() -> None:
    op.drop_index("ux_fim_scopes_agent", table_name="fim_scopes")
    op.drop_index("ux_fim_scopes_global", table_name="fim_scopes")
    op.drop_table("fim_scopes")
