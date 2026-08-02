"""
LokiLinux — Policy ORM model.

policy_type stored as VARCHAR (not native PG enum) so string `.value` comparisons
in the router work without casting.  created_by is a UUID without FK because
users are managed by Better Auth.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from lokilinux.db import Base


class Policy(Base):
    __tablename__ = "policies"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String)
    policy_type: Mapped[str | None] = mapped_column(String(50))  # UPDATE / SECURITY / COMPLIANCE / MAINTENANCE / PLUGIN
    rules: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    target_servers: Mapped[dict | None] = mapped_column(JSONB)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    parent_policy_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("policies.id"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))  # Better Auth user — no FK
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), nullable=False)

    # ── Phase 1 automation (migration 023) ──────────────────────────────────
    trigger_type: Mapped[str] = mapped_column(String(30), default="MANUAL", nullable=False)  # MANUAL / SCHEDULE
    cron_expr: Mapped[str | None] = mapped_column(String(100))
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # list of {type, params} — Phase 1 executes only actions[0]; kept as a
    # list so multi-step orchestration doesn't need another migration later.
    actions: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb"))
    # {requires_approval?: bool, timeout_seconds?: int} today
    execution: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    severity: Mapped[str | None] = mapped_column(String(20))
    tags: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb"))


class PolicyAudit(Base):
    __tablename__ = "policy_audit"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    policy_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("policies.id", ondelete="CASCADE"), nullable=False, index=True)
    changed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))  # Better Auth user — no FK
    change_type: Mapped[str] = mapped_column(String(50), nullable=False)  # CREATE / UPDATE / DELETE / ENABLE / DISABLE
    old_value: Mapped[dict | None] = mapped_column(JSONB)
    new_value: Mapped[dict | None] = mapped_column(JSONB)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), nullable=False, index=True)
