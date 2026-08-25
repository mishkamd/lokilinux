"""
LokiLinux — Alert ORM models.

AlertRule has a self-referential FK for escalation chains.
Alert references agents, jobs, policies, cves (by cve_id string), and alert_rules.
acknowledged_by / resolved_by are UUID without FK — Better Auth users.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from lokilinux.db import Base


class AlertRule(Base):
    __tablename__ = "alert_rules"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    conditions: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    alert_severity: Mapped[str | None] = mapped_column(String(50))  # CRITICAL / HIGH / MEDIUM / LOW / INFO
    notification_channels: Mapped[dict | None] = mapped_column(JSONB)
    escalation_policy: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("alert_rules.id"))
    escalation_delay_minutes: Mapped[int | None] = mapped_column(Integer)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))  # Better Auth user — no FK
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), nullable=False)


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    severity: Mapped[str | None] = mapped_column(String(50))  # CRITICAL / HIGH / MEDIUM / LOW / INFO
    alert_type: Mapped[str | None] = mapped_column(String(100))  # AGENT_OFFLINE / CVE_CRITICAL / POLICY_VIOLATION / JOB_FAILED
    description: Mapped[str | None] = mapped_column(Text)
    context_data: Mapped[dict | None] = mapped_column(JSONB)

    # Related resources
    agent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("agents.id", ondelete="SET NULL"))
    cve_id: Mapped[str | None] = mapped_column(String(50), ForeignKey("cves.cve_id", ondelete="SET NULL"))
    job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="SET NULL"))
    policy_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("policies.id", ondelete="SET NULL"))
    rule_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("alert_rules.id", ondelete="SET NULL"))
    incident_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("incidents.id", ondelete="SET NULL"))

    # Status & resolution
    status: Mapped[str] = mapped_column(String(50), default="ACTIVE", nullable=False)  # ACTIVE / ACKNOWLEDGED / RESOLVED / EXPIRED
    acknowledged_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))  # Better Auth user — no FK
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))  # Better Auth user — no FK
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Notification tracking
    notification_channels: Mapped[dict | None] = mapped_column(JSONB)
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Escalation
    escalation_level: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    triggered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), nullable=False)
