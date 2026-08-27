"""
LokiLinux — Compliance framework mapping ORM models (docs/compliance §19).

Framework -> FrameworkVersion -> Control -> RuleMapping is the queryable
normalization of compliance_rules.standard_refs (the raw JSONB captured at
import time); standard_refs stays as-is as the import source of truth, these
tables are what the Rule Catalog's framework filter and rule detail page
actually query. Framework keys (CIS/NIST/STIG/PCI_DSS/ISO27001/...) are data,
not an enum, so a customer's INTERNAL framework needs no code change.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from lokilinux.db import Base


class ComplianceFramework(Base):
    __tablename__ = "compliance_frameworks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    key: Mapped[str] = mapped_column(String(30), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), nullable=False)
    # Migration 040 (Enterprise Compliance plan U8/KTD6) — optional, no
    # backfill; UI falls back to key/name alone when unset.
    publisher: Mapped[str | None] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str | None] = mapped_column(String(20))


class ComplianceFrameworkVersion(Base):
    __tablename__ = "compliance_framework_versions"
    __table_args__ = (UniqueConstraint("framework_id", "version", name="uq_framework_versions_framework_version"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    framework_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("compliance_frameworks.id", ondelete="CASCADE"), nullable=False)
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), nullable=False)


class ComplianceControl(Base):
    __tablename__ = "compliance_controls"
    __table_args__ = (UniqueConstraint("framework_version_id", "control_id", name="uq_controls_framework_version_control"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    framework_version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("compliance_framework_versions.id", ondelete="CASCADE"), nullable=False)
    control_id: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)


class ComplianceRuleMapping(Base):
    __tablename__ = "compliance_rule_mappings"

    rule_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("compliance_rules.id", ondelete="CASCADE"), primary_key=True)
    control_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("compliance_controls.id", ondelete="CASCADE"), primary_key=True)
