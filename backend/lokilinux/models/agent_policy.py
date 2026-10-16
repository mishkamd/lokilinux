"""
LokiLinux — Agent Policy Management ORM models.

Desired-state policies for the agent fleet (plan:
docs/superpowers/plans/2026-08-23-agent-policy-modernization-plan.md).

Naming convention: `AgentPolicy` (NOT `Policy`, which is the pre-existing
cron automation model in models/policy.py). Every table carries tenant_id —
single-tenant MVP, schema-ready for real tenancy later.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from lokilinux.db import Base


class PolicyStatus(str, enum.Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"


class VersionStatus(str, enum.Enum):
    DRAFT = "draft"
    PUBLISHED = "published"


class DeploymentStatus(str, enum.Enum):
    PENDING = "pending"
    DELIVERED = "delivered"
    APPLIED = "applied"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


class ScopeType(str, enum.Enum):
    AGENT = "AGENT"
    GROUP = "GROUP"
    TENANT = "TENANT"


class RolloutStrategy(str, enum.Enum):
    IMMEDIATE = "immediate"
    CANARY = "canary"  # reserved (Faza 4+)
    PERCENTAGE = "percentage"  # reserved


class AgentPolicy(Base):
    __tablename__ = "agent_policies"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[str] = mapped_column(Text, nullable=False, server_default="default")
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="draft")
    current_version: Mapped[int | None] = mapped_column(Integer)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), nullable=False)


class AgentPolicyVersion(Base):
    """IMMUTABLE once published — edits create a new version."""

    __tablename__ = "agent_policy_versions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    policy_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_policies.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    payload_hash: Mapped[str] = mapped_column(Text, nullable=False)  # sha256 of canonical JSON bytes
    signature: Mapped[str] = mapped_column(Text, nullable=False, server_default="")  # base64 ed25519
    signing_key_id: Mapped[str] = mapped_column(Text, nullable=False, server_default="policy-signing-v1")
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="draft")
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), nullable=False)


class AgentGroup(Base):
    __tablename__ = "agent_groups"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[str] = mapped_column(Text, nullable=False, server_default="default")
    name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), nullable=False)


class AgentPolicyAssignment(Base):
    __tablename__ = "agent_policy_assignments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[str] = mapped_column(Text, nullable=False, server_default="default")
    policy_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_policies.id", ondelete="CASCADE"), nullable=False
    )
    # NULL = follow the policy's current_version pointer
    version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_policy_versions.id", ondelete="CASCADE")
    )
    scope_type: Mapped[str] = mapped_column(String(10), nullable=False, server_default="AGENT")
    scope_ref: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    rollout_strategy: Mapped[str] = mapped_column(String(20), nullable=False, server_default="immediate")
    rollout_config: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), nullable=False)


class AgentPolicyDeployment(Base):
    __tablename__ = "agent_policy_deployments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[str] = mapped_column(Text, nullable=False, server_default="default")
    assignment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_policy_assignments.id", ondelete="CASCADE"), nullable=False
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_policy_versions.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="pending")
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EnrollmentToken(Base):
    """DB-backed enrollment token (hash-only storage). Supersedes the Redis
    TTL-only token once Faza 3 wires register onto this table."""

    __tablename__ = "enrollment_tokens"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[str] = mapped_column(Text, nullable=False, server_default="default")
    token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)  # sha256 hex
    label: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    single_use: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    agent_group: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("agent_groups.id", ondelete="SET NULL"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), nullable=False)


class AgentPolicyAudit(Base):
    __tablename__ = "agent_policy_audit"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    actor: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    resource_type: Mapped[str] = mapped_column(Text, nullable=False)
    resource_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    old_version: Mapped[int | None] = mapped_column(Integer)
    new_version: Mapped[int | None] = mapped_column(Integer)
    result: Mapped[str] = mapped_column(String(10), nullable=False, server_default="ok")
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), nullable=False)


class AgentPolicyStatus(str, enum.Enum):
    IDLE = "idle"
    SYNCING = "syncing"
    PENDING = "pending"
    FAILED = "failed"
