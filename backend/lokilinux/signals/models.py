"""
LokiLinux — Signal / CorrelationRule ORM models (Phase B).

Signal is operational state: one row per (tenant_id, fingerprint), upserted
as occurrences arrive — see services/signal_service.py::upsert_signal. Raw
occurrences are append-only in ClickHouse (Task A1's signal_occurrences
table), never here.

`metadata_` maps to the DB column `metadata` — `metadata` itself is reserved
on every SQLAlchemy declarative model (Base.metadata is the MetaData
registry), so the Python attribute needs a trailing underscore.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from lokilinux.db import Base


class Signal(Base):
    __tablename__ = "signals"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[str] = mapped_column(Text(), nullable=False, server_default="default")
    type: Mapped[str] = mapped_column(Text(), nullable=False)
    severity: Mapped[str] = mapped_column(Text(), nullable=False)
    status: Mapped[str] = mapped_column(Text(), nullable=False, server_default="OPEN")  # OPEN|RESOLVED|SUPPRESSED
    host_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    service: Mapped[str | None] = mapped_column(Text())
    fingerprint: Mapped[str] = mapped_column(Text(), nullable=False)
    occurrence_count: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="1")
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_event_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb"))


class CorrelationRule(Base):
    __tablename__ = "correlation_rules"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[str] = mapped_column(Text(), nullable=False, server_default="default")
    name: Mapped[str] = mapped_column(Text(), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean(), nullable=False, server_default=text("true"))
    window_seconds: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="300")
    group_by: Mapped[list] = mapped_column(JSONB, nullable=False)
    conditions: Mapped[list] = mapped_column(JSONB, nullable=False)
    threshold_score: Mapped[int] = mapped_column(Integer(), nullable=False)
    incident_type: Mapped[str] = mapped_column(Text(), nullable=False)
    incident_severity: Mapped[str] = mapped_column(Text(), nullable=False)
    suppressions: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    version: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="1")
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), nullable=False)
