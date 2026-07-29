"""
LokiLinux — Remediation Engine ORM models.

remediation_jobs is a thin join to the existing jobs table (models/job.py) —
dedup, per-agent fan-out, and status aggregation are 100% JobService's;
this module only tracks which plan a job serves, mirroring
AgentVulnerability.remediation_job_id's existing finding-to-job pattern.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from lokilinux.db import Base


class MaintenanceWindow(Base):
    __tablename__ = "maintenance_windows"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    scope_type: Mapped[str] = mapped_column(String(20), default="GLOBAL", nullable=False)
    scope_selector: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    cron_expr: Mapped[str | None] = mapped_column(String(100))
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    timezone: Mapped[str] = mapped_column(String(50), default="UTC", nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), nullable=False)


class RemediationPlan(Base):
    __tablename__ = "remediation_plans"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="DRAFT", nullable=False)
    trigger_type: Mapped[str] = mapped_column(String(20), nullable=False)  # MANUAL/SCHEDULED/AUTOMATIC/AI_SUGGESTED
    maintenance_window_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("maintenance_windows.id"))
    is_emergency: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), nullable=False)


class RemediationAction(Base):
    __tablename__ = "remediation_actions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    remediation_plan_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("remediation_plans.id", ondelete="CASCADE"), nullable=False)
    rule_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("compliance_rules.id"))
    drift_event_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))  # no FK — drift_events is a hypertable
    agent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    provider: Mapped[str] = mapped_column(String(20), nullable=False)  # ansible/shell/python/terraform
    rendered_body: Mapped[str] = mapped_column(Text, nullable=False)
    rollback_body: Mapped[str | None] = mapped_column(Text)
    sequence: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class RemediationJob(Base):
    __tablename__ = "remediation_jobs"

    remediation_plan_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("remediation_plans.id", ondelete="CASCADE"), primary_key=True)
    job_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), primary_key=True)
