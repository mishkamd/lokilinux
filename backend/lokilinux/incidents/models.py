"""
LokiLinux — Incident / IncidentSignal / IncidentTimeline ORM models (Phase D).

`metadata_` maps to the DB column `metadata` — same reserved-word escape as
signals/models.py::Signal.metadata_ (Base.metadata is SQLAlchemy's own
MetaData registry, so the Python attribute name can't literally be
"metadata" on any declarative model).
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from lokilinux.db import Base


class Incident(Base):
    __tablename__ = "incidents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[str] = mapped_column(Text(), nullable=False, server_default="default")
    title: Mapped[str] = mapped_column(Text(), nullable=False)
    type: Mapped[str] = mapped_column(Text(), nullable=False)
    severity: Mapped[str] = mapped_column(Text(), nullable=False)
    status: Mapped[str] = mapped_column(Text(), nullable=False, server_default="OPEN")
    root_cause_signal_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("signals.id", ondelete="SET NULL"))
    confidence: Mapped[float | None] = mapped_column(Float())
    group_key: Mapped[str | None] = mapped_column(Text())
    correlation_rule_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("correlation_rules.id", ondelete="SET NULL"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb"))


class IncidentSignal(Base):
    __tablename__ = "incident_signals"

    incident_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("incidents.id", ondelete="CASCADE"), primary_key=True)
    signal_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("signals.id", ondelete="CASCADE"), primary_key=True)


class IncidentTimeline(Base):
    __tablename__ = "incident_timeline"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    incident_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), nullable=False)
    kind: Mapped[str] = mapped_column(Text(), nullable=False)  # created|signal|transition|runbook|note
    message: Mapped[str] = mapped_column(Text(), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
