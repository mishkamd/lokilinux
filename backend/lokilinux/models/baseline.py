"""
LokiLinux — Baseline Manager ORM models (Compliance module).

Scope tree (scope_type + scope_selector) rather than a fixed hierarchy of
columns — real fleets don't always nest cleanly, and a datacenter-scope rule
and a cluster-scope rule can both apply to the same host without one
containing the other. See docs/compliance/06-BASELINE.md for the merge
algorithm that resolves baseline_effective from baselines + baseline_versions.

baseline_effective is a materialized cache, not a source of truth — safe to
drop and recompute at any time from published baseline_versions rows.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import ARRAY, BYTEA, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from lokilinux.db import Base


class Baseline(Base):
    __tablename__ = "baselines"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    scope_type: Mapped[str] = mapped_column(String(20), nullable=False)  # GLOBAL/OS/ROLE/ENVIRONMENT/DATACENTER/CLUSTER/APPLICATION
    scope_selector: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    parent_baseline_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("baselines.id"))
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))  # Better Auth user — no FK
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), nullable=False)


class BaselineVersion(Base):
    __tablename__ = "baseline_versions"
    __table_args__ = (UniqueConstraint("baseline_id", "version", name="uq_baseline_versions_baseline_version"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    baseline_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("baselines.id", ondelete="CASCADE"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="DRAFT", nullable=False)  # DRAFT/PENDING_APPROVAL/APPROVED/PUBLISHED/DEPRECATED
    expected_state: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    signature: Mapped[bytes | None] = mapped_column(BYTEA)
    signed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    change_summary: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deprecated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BaselineApproval(Base):
    __tablename__ = "baseline_approvals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    baseline_version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("baseline_versions.id", ondelete="CASCADE"), nullable=False, index=True)
    approver_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    decision: Mapped[str] = mapped_column(String(20), nullable=False)  # APPROVED/REJECTED
    comment: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), nullable=False)


class BaselineEffective(Base):
    __tablename__ = "baseline_effective"

    agent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True)
    baseline_version_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), nullable=False)
    merged_state: Mapped[dict] = mapped_column(JSONB, nullable=False)
    merged_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), nullable=False)
