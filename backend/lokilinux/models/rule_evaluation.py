"""
LokiLinux — Compliance rule evaluation + scoring ORM models.

Both tables are TimescaleDB hypertables (created via create_hypertable in
the migration, space-partitioned on agent_id) — these Mapped classes only
describe columns/PK for the ORM layer; storage settings (compression,
retention, continuous aggregates) live in the migration, not here.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from lokilinux.db import Base


class RuleEvaluation(Base):
    __tablename__ = "rule_evaluations"

    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    agent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    rule_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    policy_set_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    result: Mapped[str] = mapped_column(String(20), nullable=False)  # PASS/FAIL/ERROR/NOT_APPLICABLE/NOT_EVALUATED
    actual_value: Mapped[dict | None] = mapped_column(JSONB)
    evidence: Mapped[dict | None] = mapped_column(JSONB)
    error_message: Mapped[str | None] = mapped_column(Text)
    # Migration 025 — structured evidence provenance (docs/compliance §21).
    expected_value: Mapped[dict | None] = mapped_column(JSONB)
    evidence_hash: Mapped[str | None] = mapped_column(String(64))
    source: Mapped[str | None] = mapped_column(String(50))
    agent_version: Mapped[str | None] = mapped_column(String(50))
    # Set when an active compliance_exceptions row covered this verdict — the
    # real FAIL result is still stored, never silently overwritten (§17).
    exception_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    # Migration 039 (Enterprise Compliance plan U4) — finding-level
    # acknowledgment, same shape as DriftEvent.acknowledged_by/at.
    acknowledged_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ComplianceScore(Base):
    __tablename__ = "compliance_scores"

    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    agent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    category: Mapped[str] = mapped_column(String(30), primary_key=True)  # overall/security/configuration/filesystem/packages/kernel
    score: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    passed_count: Mapped[int] = mapped_column(Integer, nullable=False)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False)
    not_applicable_count: Mapped[int] = mapped_column(Integer, nullable=False)
