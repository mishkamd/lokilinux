"""
LokiLinux — Async fleet assessment job ORM model (docs/compliance §24).

Progress is fanned out through the existing JobService (backend/lokilinux/
services/job_service.py) — this table only tracks the assessment-level
aggregate (servers_total/done, rules_total/done), not a second job queue.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from lokilinux.db import Base


class ComplianceAssessment(Base):
    __tablename__ = "compliance_assessments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    scope_selector: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    policy_set_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("policy_sets.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(20), default="PENDING", nullable=False)  # PENDING/RUNNING/COMPLETED/FAILED/CANCELLED
    servers_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    servers_done: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rules_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rules_done: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
