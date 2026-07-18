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

    model_config = {"from_attributes": True}


CVEListResponse = CursorPage[CVEResponse]


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
    cve_id: str
    package_name: str
    package_version: str
    cvss_score: float | None = None
    severity: CVESeverity | None = None
    fix_available: bool = False
    is_remediated: bool = False
    discovered_at: datetime

    model_config = {"from_attributes": True}


VulnerabilityListResponse = CursorPage[VulnerabilityResponse]
