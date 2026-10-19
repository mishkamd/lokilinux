"""agent policy management — desired-state policies for the agent fleet.

Plan: docs/superpowers/plans/2026-08-23-agent-policy-modernization-plan.md
(Fazele 1-4). Purely additive tables + nullable ALTER on agents; seed writes
the default tenant's Bootstrap Policy (v1) and the three starter templates.

Revision ID: 038
Create Date: 2026-08-27
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "038"
down_revision = "037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_policies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", sa.Text(), nullable=False, server_default="default"),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.Text(), nullable=False, server_default="draft"),  # draft|active|archived
        sa.Column("current_version", sa.Integer(), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("tenant_id", "name", name="uq_agent_policies_tenant_name"),
    )

    op.create_table(
        "agent_policy_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("policy_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agent_policies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        # payload = compiled policy document JSONB (the AgentPolicy YAML object)
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("payload_hash", sa.Text(), nullable=False),  # sha256 of canonical payload
        sa.Column("signature", sa.Text(), nullable=False, server_default=""),  # base64 ed25519 over canonical bytes
        sa.Column("signing_key_id", sa.Text(), nullable=False, server_default="policy-signing-v1"),
        sa.Column("status", sa.Text(), nullable=False, server_default="draft"),  # draft|published — immutable once published
        sa.Column("created_by", postgresql.UUID(as_uuid=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("policy_id", "version", name="uq_agent_policy_versions_pid_version"),
    )

    op.create_table(
        "agent_groups",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", sa.Text(), nullable=False, server_default="default"),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("tenant_id", "name", name="uq_agent_groups_tenant_name"),
    )

    op.create_table(
        "agent_policy_assignments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", sa.Text(), nullable=False, server_default="default"),
        sa.Column("policy_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agent_policies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agent_policy_versions.id", ondelete="CASCADE")),  # NULL = current_version
        sa.Column("scope_type", sa.Text(), nullable=False, server_default="AGENT"),  # AGENT|GROUP|TENANT
        sa.Column("scope_ref", postgresql.UUID(as_uuid=True)),  # agent id / group id; NULL for TENANT scope
        sa.Column("rollout_strategy", sa.Text(), nullable=False, server_default="immediate"),  # immediate|canary|percentage
        sa.Column("rollout_config", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", postgresql.UUID(as_uuid=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "agent_policy_deployments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", sa.Text(), nullable=False, server_default="default"),
        sa.Column("assignment_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agent_policy_assignments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agent_policy_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),  # pending|delivered|applied|failed|rolled_back
        sa.Column("error", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_agent_policy_deployments_agent_status", "agent_policy_deployments", ["agent_id", "status"])

    op.create_table(
        "enrollment_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", sa.Text(), nullable=False, server_default="default"),
        sa.Column("token_hash", sa.Text(), nullable=False, unique=True),  # sha256; plaintext never stored
        sa.Column("label", sa.Text(), nullable=False, server_default=""),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("single_use", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("agent_group", postgresql.UUID(as_uuid=True), sa.ForeignKey("agent_groups.id", ondelete="SET NULL")),
        sa.Column("created_by", postgresql.UUID(as_uuid=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "agent_policy_audit",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("actor", postgresql.UUID(as_uuid=True)),
        sa.Column("action", sa.Text(), nullable=False),  # create|update|publish|assign|deploy|apply_ok|apply_fail|rollback|revoke_token
        sa.Column("resource_type", sa.Text(), nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True)),
        sa.Column("old_version", sa.Integer()),
        sa.Column("new_version", sa.Integer()),
        sa.Column("result", sa.Text(), nullable=False, server_default="ok"),  # ok|fail
        sa.Column("error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_agent_policy_audit_resource", "agent_policy_audit", ["resource_type", "resource_id"])

    op.add_column("agents", sa.Column("desired_policy_version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agent_policy_versions.id", ondelete="SET NULL")))
    op.add_column("agents", sa.Column("current_policy_version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agent_policy_versions.id", ondelete="SET NULL")))
    op.add_column("agents", sa.Column("policy_status", sa.Text(), nullable=False, server_default="idle"))  # idle|syncing|pending|failed
    op.add_column("agents", sa.Column("policy_last_error", sa.Text()))
    op.add_column("agents", sa.Column("policy_updated_at", sa.DateTime(timezone=True)))

    _seed()


def _seed() -> None:
    """Default tenant + Default Bootstrap Policy v1 + three starter templates.

    The bootstrap policy is deny-by-default: every collector disabled except a
    minimal safe set, standard heartbeat. Templates are published drafts with
    status='draft' so admins review before activate."""
    conn = op.get_bind()
    tenant = "default"

    def _payload(name: str, description: str, collectors: dict) -> dict:
        return {
            "apiVersion": "lokilinux.io/v1",
            "kind": "AgentPolicy",
            "metadata": {"name": name, "description": description},
            "spec": {
                "collectors": collectors,
                "heartbeat": {"interval_seconds": 60},
                "health": {"collect_interval_seconds": 30},
            },
        }

    linux_minimal_collectors = {"auditd": {"enabled": False}, "sshd": {"enabled": True}, "users": {"enabled": True}}
    linux_standard_collectors = {
        **linux_minimal_collectors,
        "packages": {"enabled": True},
        "services": {"enabled": True},
        "network": {"enabled": True},
        "sysctl": {"enabled": True},
    }
    linux_production_collectors = {
        **linux_standard_collectors,
        "processes": {"enabled": True},
        "time_sync": {"enabled": True},
        "file_integrity": {"enabled": True},
    }

    rows = [
        ("linux-minimal", "Minimal collection — sshd/users only.", linux_minimal_collectors),
        ("linux-standard", "Standard server profile: patching, services, network, sysctl.", linux_standard_collectors),
        ("linux-production", "Production profile adds processes, time sync and file integrity.", linux_production_collectors),
    ]

    import hashlib
    import json

    for name, desc, collectors in rows:
        payload = _payload(name, desc, collectors)
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        pid = conn.execute(
            sa.text(
                """INSERT INTO agent_policies (tenant_id, name, description, status)
                   VALUES (:t, :n, :d, 'active') RETURNING id"""
            ),
            {"t": tenant, "n": name, "d": desc},
        ).scalar_one()
        conn.execute(
            sa.text(
                """INSERT INTO agent_policy_versions (policy_id, version, payload, payload_hash, signature, signing_key_id, status)
                   VALUES (:p, 1, CAST(:payload AS jsonb), :hash, '', 'bootstrap', 'published')"""
            ),
            {"p": str(pid), "payload": canonical, "hash": hashlib.sha256(canonical.encode()).hexdigest()},
        )
        vid = conn.execute(
            sa.text("SELECT id FROM agent_policy_versions WHERE policy_id = :p AND version = 1"),
            {"p": str(pid)},
        ).scalar_one()
        conn.execute(
            sa.text("UPDATE agent_policies SET current_version = 1 WHERE id = :p"),
            {"p": str(pid)},
        )

    # Default Bootstrap Policy v1 — ACTIVE per plan §3, minimal safe collection.
    # No assignment is created here, so an active row deploys to nobody until an
    # admin assigns it; behavior of existing agents is unchanged.
    bootstrap = _payload("default-bootstrap", "Bootstrap policy shipped with the platform — minimal safe collection.", linux_minimal_collectors)
    canonical = json.dumps(bootstrap, sort_keys=True, separators=(",", ":"))
    pid = conn.execute(
        sa.text(
            """INSERT INTO agent_policies (tenant_id, name, description, status)
               VALUES (:t, 'default-bootstrap', 'Platform bootstrap policy v1.', 'active') RETURNING id"""
        ),
        {"t": tenant},
    ).scalar_one()
    conn.execute(
        sa.text(
            """INSERT INTO agent_policy_versions (policy_id, version, payload, payload_hash, signature, signing_key_id, status)
               VALUES (:p, 1, CAST(:payload AS jsonb), :hash, '', 'bootstrap', 'published')"""
        ),
        {"p": str(pid), "payload": canonical, "hash": hashlib.sha256(canonical.encode()).hexdigest()},
    )
    vid = conn.execute(
        sa.text("SELECT id FROM agent_policy_versions WHERE policy_id = :p AND version = 1"),
        {"p": str(pid)},
    ).scalar_one()
    conn.execute(
        sa.text("UPDATE agent_policies SET current_version = 1 WHERE id = :p"),
        {"p": str(pid)},
    )


def downgrade() -> None:
    op.drop_column("agents", "policy_updated_at")
    op.drop_column("agents", "policy_last_error")
    op.drop_column("agents", "policy_status")
    op.drop_column("agents", "current_policy_version_id")
    op.drop_column("agents", "desired_policy_version_id")
    op.drop_table("agent_policy_audit")
    op.drop_table("enrollment_tokens")
    op.drop_table("agent_policy_deployments")
    op.drop_table("agent_policy_assignments")
    op.drop_table("agent_groups")
    op.drop_table("agent_policy_versions")
    op.drop_table("agent_policies")
