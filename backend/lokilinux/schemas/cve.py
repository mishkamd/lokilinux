"""
LokiLinux — CVE / Vulnerability Pydantic schemas.
"""

from datetime import date, datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel

from lokilinux.schemas.common import CursorPage


class CVESeverity(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class VulnerabilityStatus(str, Enum):
    OPEN = "OPEN"
    PATCH_AVAILABLE = "PATCH_AVAILABLE"
    IN_PROGRESS = "IN_PROGRESS"
    MITIGATED = "MITIGATED"
    RESOLVED = "RESOLVED"
    ACCEPTED_RISK = "ACCEPTED_RISK"


class CVEResponse(BaseModel):
    id: int
    cve_id: str
    title: str | None = None
    description: str | None = None
    cvss_v3_score: float | None = None
    cvss_v3_severity: CVESeverity | None = None
    published_date: date | None = None
    is_zero_day: bool = False
    is_actively_exploited: bool = False
    affected_packages: dict | None = None
    affected_count: int = 0  # not a DB column — set by the router from a GROUP BY

    model_config = {"from_attributes": True}


class CVESummary(BaseModel):
    CRITICAL: int = 0
    HIGH: int = 0
    MEDIUM: int = 0
    LOW: int = 0


class CVEListResponse(CursorPage[CVEResponse]):
    summary: CVESummary


class PackageResponse(BaseModel):
    id: int
    name: str
    version: str
    architecture: str | None = None
    repository: str | None = None
    is_security_update_available: bool = False
    is_update_available: bool = False
    latest_version: str | None = None

    model_config = {"from_attributes": True}


class VulnerabilityResponse(BaseModel):
    id: int
    agent_id: UUID
    hostname: str | None = None
    cve_id: str
    package_name: str
    package_version: str
    fixed_version: str | None = None
    cvss_score: float | None = None
    severity: CVESeverity | None = None
    fix_available: bool = False
    is_remediated: bool = False
    status: VulnerabilityStatus = VulnerabilityStatus.OPEN
    discovered_at: datetime
    last_scan_at: datetime | None = None

    model_config = {"from_attributes": True}


class VulnerabilitySummaryResponse(BaseModel):
    """Overview KPI row (docs/vulnerabilities). Counts are OPEN findings
    (status not in RESOLVED/ACCEPTED_RISK) — a resolved or accepted-risk
    finding shouldn't inflate "how exposed is the fleet right now"."""

    resources_scanned: int
    resources_total: int
    critical: int
    high: int
    medium: int
    low: int
    # Delta vs the same-length prior period (e.g. this 7d window vs the 7d
    # before it) — None when there's no prior-period data to compare against
    # rather than a fabricated 0%.
    critical_delta_pct: float | None = None
    high_delta_pct: float | None = None
    medium_delta_pct: float | None = None


class VulnerabilityTrendPoint(BaseModel):
    day: date
    critical: int
    high: int
    medium: int
    low: int


class TopVulnerableResource(BaseModel):
    agent_id: UUID
    hostname: str | None = None
    environment: str | None = None  # categories.name
    project: str | None = None
    os_distro: str | None = None
    os_version: str | None = None
    critical: int
    high: int
    medium: int
    low: int
    total: int


class PatchableVulnerability(BaseModel):
    cve_id: str
    cvss_v3_score: float | None = None
    cvss_v3_severity: CVESeverity | None = None
    package_name: str
    fixed_version: str | None = None
    affected_count: int


class VulnerabilityResourceDetail(BaseModel):
    """One agent's finding for a CVE — the "Affected Resources" table on a
    CVE detail page."""

    agent_id: UUID
    hostname: str | None = None
    ip: str | None = None  # last_heartbeat_ip — the closest thing agents has to a tracked IP
    os_distro: str | None = None
    os_version: str | None = None
    package_name: str
    package_version: str
    fixed_version: str | None = None
    environment: str | None = None
    project: str | None = None
    last_scan_at: datetime | None = None
    status: VulnerabilityStatus = VulnerabilityStatus.OPEN


class AcceptRiskRequest(BaseModel):
    reason: str
    until: datetime | None = None
    agent_ids: list[UUID] | None = None  # None = accept across every affected resource


VulnerabilityListResponse = CursorPage[VulnerabilityResponse]
