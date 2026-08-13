"""
LokiLinux — CVE / vulnerability ORM models.

CVE.id is INTEGER (SERIAL) — the router cursor uses int() on it.
CVE.cve_id is the human identifier (CVE-YYYY-NNNNN).
Column names cvss_v3_score / cvss_v3_severity match CVEResponse schema.
AgentVulnerability.id is also INTEGER — VulnerabilityResponse.id: int.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from lokilinux.db import Base


class CVE(Base):
    __tablename__ = "cves"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cve_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)  # CVE-YYYY-XXXXX

    # Details
    title: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    cvss_v3_score: Mapped[float | None] = mapped_column(Float)
    cvss_v3_severity: Mapped[str | None] = mapped_column(String(20))  # CRITICAL / HIGH / MEDIUM / LOW
    published_date: Mapped[date | None] = mapped_column(Date)
    updated_date: Mapped[date | None] = mapped_column(Date)

    # References
    nvd_url: Mapped[str | None] = mapped_column(String(255))
    debian_url: Mapped[str | None] = mapped_column(String(255))
    ubuntu_url: Mapped[str | None] = mapped_column(String(255))
    redhat_url: Mapped[str | None] = mapped_column(String(255))

    # Classification
    cwe_ids: Mapped[list] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    affected_packages: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))

    is_zero_day: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_actively_exploited: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    kev_date_added: Mapped[date | None] = mapped_column(Date)  # CISA Known Exploited Vulnerabilities

    # NVD enrichment tracking — PENDING/OK/NOT_FOUND/ERROR, makes the
    # backfill worker resumable: it only re-queries PENDING rows.
    enrichment_status: Mapped[str] = mapped_column(String(20), default="PENDING", nullable=False)
    last_enriched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), nullable=False)


class Package(Base):
    __tablename__ = "packages"
    __table_args__ = (UniqueConstraint("agent_id", "name", "version", name="uq_packages_agent_name_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True)

    # Package identity — column names match PackageResponse schema
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    version: Mapped[str] = mapped_column(String(100), nullable=False)
    architecture: Mapped[str | None] = mapped_column(String(50))
    repository: Mapped[str | None] = mapped_column(String(255))
    source_type: Mapped[str | None] = mapped_column(String(50))  # manual / distro / ppa

    # Update status
    is_update_available: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_security_update_available: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    latest_version: Mapped[str | None] = mapped_column(String(100))

    installed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_update_check: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), nullable=False)


class PackageVulnerability(Base):
    """CVE ↔ package mapping (distro-specific, not per-agent)."""

    __tablename__ = "package_vulnerabilities"
    __table_args__ = (UniqueConstraint("cve_id", "package_name", "distro", name="uq_pkg_vuln_cve_pkg_distro"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cve_id: Mapped[str] = mapped_column(String(50), ForeignKey("cves.cve_id", ondelete="CASCADE"), nullable=False, index=True)
    package_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    distro: Mapped[str] = mapped_column(String(100), nullable=False)  # debian / ubuntu / rhel / rocky
    affected_versions: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    fixed_version: Mapped[str | None] = mapped_column(String(100))
    is_fixed_available: Mapped[bool | None] = mapped_column(Boolean)
    fix_available_date: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), nullable=False)


class AgentVulnerability(Base):
    """Vulnerability detected on a specific agent — per VulnerabilityResponse schema."""

    __tablename__ = "agent_vulnerabilities"
    __table_args__ = (
        UniqueConstraint("agent_id", "cve_id", "package_name", name="uq_agent_vuln_agent_cve_package"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True)
    cve_id: Mapped[str] = mapped_column(String(50), ForeignKey("cves.cve_id", ondelete="CASCADE"), nullable=False, index=True)

    # Affected package on this agent
    package_name: Mapped[str] = mapped_column(String(255), nullable=False)
    package_version: Mapped[str] = mapped_column(String(100), nullable=False)

    # Risk
    cvss_score: Mapped[float | None] = mapped_column(Float)
    severity: Mapped[str | None] = mapped_column(String(20))
    risk_score: Mapped[float | None] = mapped_column(Float)

    # Remediation
    fixed_version: Mapped[str | None] = mapped_column(String(100))
    fix_available: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    recommended_action: Mapped[str | None] = mapped_column(String(50))  # patch / upgrade / monitor / retire
    is_remediated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    remediation_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    remediation_job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("jobs.id"))
    remediation_plan_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("remediation_plans.id"))

    # Lifecycle — source of truth going forward; is_remediated is kept for
    # existing readers/writers (agent_service, dashboard.py) but new code
    # should read/write status.
    status: Mapped[str] = mapped_column(String(20), default="OPEN", nullable=False)
    # Accept-risk (mirrors compliance_exceptions' shape)
    accepted_risk_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    accepted_risk_reason: Mapped[str | None] = mapped_column(Text)
    accepted_risk_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), nullable=False)
    last_check: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    # Set only when this agent's heartbeat carried a real, non-empty
    # vulnerability report — distinguishes "verified present in the last
    # scan" from "row just hasn't been touched since a stale heartbeat".
    last_scan_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
