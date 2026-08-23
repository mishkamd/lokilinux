"""
LokiLinux — Workflow Engine ORM models.

A workflow is a DAG of steps, defined declaratively in YAML (workflow_versions.
yaml_source, the authoritative form for humans and Git) plus a parsed/validated
`graph` JSONB (the form the engine reads, so it never re-parses YAML per tick —
see services/workflow_compiler.py). Versions are immutable once PUBLISHED,
mirroring BaselineVersion (models/baseline.py, docs/compliance/06-BASELINE.md).

Execution never talks to agents directly: each step becomes a Job via the
existing JobService, exactly the containment RemediationService already uses
("plan workflow on top of the existing Job Engine" — services/remediation_service.py:2).
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from lokilinux.db import Base


class Workflow(Base):
    __tablename__ = "workflows"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # FK added by op.add_column after workflow_versions exists (migration 028) —
    # the two tables reference each other, so the second one wins the cycle.
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    # Same trigger/schedule vocabulary as Policy (models/policy.py:36-40) —
    # required for Workflow to be a strict superset, see the migration plan
    # in docs/compliance/... / plan §15.
    trigger_type: Mapped[str] = mapped_column(String(30), default="MANUAL", nullable=False)  # MANUAL / SCHEDULE
    cron_expr: Mapped[str | None] = mapped_column(String(100))
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    severity: Mapped[str | None] = mapped_column(String(20))
    tags: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb"))

    # Set once a Policy row has been imported as this workflow (migration
    # plan §15 stage B) — PolicySchedulerWorker skips policies with this set.
    migrated_from_policy_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("policies.id"))

    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))  # Better Auth user — no FK
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), nullable=False)


class WorkflowVersion(Base):
    __tablename__ = "workflow_versions"
    __table_args__ = (UniqueConstraint("workflow_id", "version", name="uq_workflow_versions_workflow_version"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    workflow_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    yaml_source: Mapped[str] = mapped_column(Text, nullable=False)
    # Parsed + validated form (services/workflow_compiler.py's CompiledGraph) —
    # what the engine reads; never re-parsed from yaml_source per tick.
    graph: Mapped[dict] = mapped_column(JSONB, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)  # sha256(yaml_source) — optimistic concurrency
    status: Mapped[str] = mapped_column(String(20), default="DRAFT", nullable=False)  # DRAFT / PUBLISHED / ARCHIVED
    change_summary: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    workflow_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False)
    workflow_version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("workflow_versions.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="PENDING", nullable=False)
    trigger_type: Mapped[str] = mapped_column(String(20), nullable=False)  # MANUAL / SCHEDULE / API
    triggered_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    # Resolved agent id list, frozen at start — a server added mid-run must
    # not silently receive only the remaining steps (plan §4).
    targets: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    vars: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    is_dry_run: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), nullable=False)


class WorkflowStepRun(Base):
    __tablename__ = "workflow_step_runs"
    __table_args__ = (UniqueConstraint("run_id", "step_id", "attempt", name="uq_workflow_step_runs_run_step_attempt"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("workflow_runs.id", ondelete="CASCADE"), nullable=False)
    step_id: Mapped[str] = mapped_column(String(64), nullable=False)  # the id from the YAML spec.steps[].id
    status: Mapped[str] = mapped_column(String(20), default="PENDING", nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="SET NULL"))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    output: Mapped[dict | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), nullable=False)


class WorkflowAudit(Base):
    __tablename__ = "workflow_audit"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workflow_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False, index=True)
    changed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    change_type: Mapped[str] = mapped_column(String(50), nullable=False)  # CREATE / PUBLISH / RUN / APPROVE / REJECT / CANCEL
    old_value: Mapped[dict | None] = mapped_column(JSONB)
    new_value: Mapped[dict | None] = mapped_column(JSONB)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), nullable=False, index=True)
