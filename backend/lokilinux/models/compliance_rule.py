"""
LokiLinux — Compliance Policy Engine ORM models: rule catalog, remediation
templates, policy sets/assignments.

Rule content is imported from ComplianceAsCode (docs/compliance/07-POLICY-ENGINE.md)
rather than hand-authored — source/source_version track provenance for a
reproducible re-import. check_source distinguishes CEL-evaluable rules from
OVAL_UNMAPPED/OSCAP_FALLBACK ones; coverage is computed by summing over this
column, never assumed 100%.

standard_refs (not "references" — reserved word in PostgreSQL).
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from lokilinux.db import Base


class ComplianceRule(Base):
    __tablename__ = "compliance_rules"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    rule_key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    rationale: Mapped[str | None] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)  # LOW/MEDIUM/HIGH/CRITICAL
    domain: Mapped[str] = mapped_column(String(50), nullable=False)
    check_source: Mapped[str] = mapped_column(String(20), default="CEL", nullable=False)  # CEL/OVAL_UNMAPPED/OSCAP_FALLBACK
    check_expr: Mapped[str | None] = mapped_column(Text)
    expected_value: Mapped[object | None] = mapped_column(JSONB)
    platform_filter: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb"))
    standard_refs: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    remediation_template_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("remediation_templates.id"))
    source: Mapped[str] = mapped_column(String(30), default="complianceascode", nullable=False)
    source_version: Mapped[str | None] = mapped_column(String(50))
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), nullable=False)


class RemediationTemplate(Base):
    __tablename__ = "remediation_templates"
    __table_args__ = (UniqueConstraint("rule_key", "provider", "version", name="uq_remediation_templates_rule_provider_version"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    rule_key: Mapped[str] = mapped_column(String(255), ForeignKey("compliance_rules.rule_key"), nullable=False)
    provider: Mapped[str] = mapped_column(String(20), nullable=False)  # ansible/shell/python/terraform
    body: Mapped[str] = mapped_column(Text, nullable=False)
    rollback_body: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(30), default="complianceascode", nullable=False)
    git_path: Mapped[str | None] = mapped_column(String(500))
    version: Mapped[int] = mapped_column(default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), nullable=False)


class PolicySet(Base):
    __tablename__ = "policy_sets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    framework: Mapped[str] = mapped_column(String(30), nullable=False)  # CIS/NIST/PCI_DSS/ISO27001/STIG/INTERNAL
    version: Mapped[str | None] = mapped_column(String(50))
    description: Mapped[str | None] = mapped_column(Text)
    source_profile: Mapped[str | None] = mapped_column(String(255))
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), nullable=False)
    # Migration 025 — flat immutable versioning: editing a PUBLISHED set
    # clones a new row via parent_policy_set_id rather than mutating rules
    # under an already-published version (§6).
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PUBLISHED")  # DRAFT/PUBLISHED/ARCHIVED
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    parent_policy_set_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("policy_sets.id"))


class PolicySetRule(Base):
    __tablename__ = "policy_set_rules"

    policy_set_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("policy_sets.id", ondelete="CASCADE"), primary_key=True)
    rule_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("compliance_rules.id", ondelete="CASCADE"), primary_key=True)
    severity_override: Mapped[str | None] = mapped_column(String(20))


class PolicyAssignment(Base):
    __tablename__ = "policy_assignments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    policy_set_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("policy_sets.id", ondelete="CASCADE"), nullable=False)
    scope_type: Mapped[str] = mapped_column(String(20), nullable=False)
    scope_selector: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), nullable=False)
