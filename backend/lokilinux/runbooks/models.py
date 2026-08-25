"""
LokiLinux — Runbook ORM model (Phase E).

A thin mapping row: incident_type -> workflow_id. Execution reuses the
existing Workflow Engine end to end (services/workflow_engine.py::start_run)
— this table holds no execution logic of its own.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from lokilinux.db import Base


class Runbook(Base):
    __tablename__ = "runbooks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[str] = mapped_column(Text(), nullable=False, server_default="default")
    name: Mapped[str] = mapped_column(Text(), nullable=False)
    incident_type: Mapped[str] = mapped_column(Text(), nullable=False)
    workflow_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("workflows.id", ondelete="SET NULL"))
    trigger_mode: Mapped[str] = mapped_column(Text(), nullable=False, server_default="MANUAL")  # MANUAL|AUTO
    min_severity: Mapped[str] = mapped_column(Text(), nullable=False, server_default="HIGH")
    enabled: Mapped[bool] = mapped_column(Boolean(), nullable=False, server_default=text("true"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), nullable=False)
