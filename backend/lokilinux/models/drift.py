"""
LokiLinux — Drift Detection ORM models (Compliance module).

drift_events/drift_details are TimescaleDB hypertables created directly in
migration 017 — SQLAlchemy only needs to know the columns/PK to match what's
actually on disk, same convention as models/inventory.py. Written by
lokilinux-compliance's Ingester (services/compliance/internal/ingest/ingest.go
detectDrift), read here.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from lokilinux.db import Base


class DriftEvent(Base):
    __tablename__ = "drift_events"

    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    agent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    domain: Mapped[str] = mapped_column(String(50), nullable=False)
    compared_against: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # BASELINE/PREVIOUS_SNAPSHOT/DESIRED_STATE
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    change_type: Mapped[str] = mapped_column(String(30), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    changed_by_user: Mapped[str | None] = mapped_column(String(255))
    root_cause: Mapped[dict | None] = mapped_column(JSONB)
    acknowledged_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Lifecycle + dedup (migration 025) — see services/compliance ingest.go's
    # correlation_key computation for how occurrences/first_seen/last_seen
    # are maintained instead of inserting a new row per poll cycle.
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'OPEN'")
    )  # OPEN/ACKNOWLEDGED/IN_REMEDIATION/RESOLVED/SUPPRESSED/EXCEPTION
    occurrences: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    first_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    correlation_key: Mapped[str | None] = mapped_column(String(64))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    suppressed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class DriftDetail(Base):
    __tablename__ = "drift_details"

    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    drift_event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    drift_event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    field_path: Mapped[str] = mapped_column(String(500), primary_key=True)
    old_value: Mapped[dict | None] = mapped_column(JSONB)
    new_value: Mapped[dict | None] = mapped_column(JSONB)
