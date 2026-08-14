"""
LokiLinux — Compliance exceptions/waivers ORM model.

A rule can be intentionally non-compliant on an agent (or a broader scope)
for a bounded time — docs/compliance §17. agent_id is nullable: a NULL
agent_id means the exception applies via scope_selector instead, same
scope-tree convention policy_assignments/baselines already use. Expiry is
enforced by a scheduler worker (services/compliance/internal/scheduler),
not by application-read-time checks alone — status flips ACTIVE -> EXPIRED
so the rule reverts to FAIL without waiting for a request to notice.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from lokilinux.db import Base


class ComplianceException(Base):
    __tablename__ = "compliance_exceptions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    rule_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("compliance_rules.id", ondelete="CASCADE"), nullable=False)
    agent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"))
    scope_selector: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    owner: Mapped[str] = mapped_column(String(255), nullable=False)
    requested_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="PENDING", nullable=False)  # PENDING/ACTIVE/EXPIRED/REVOKED
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), nullable=False)
