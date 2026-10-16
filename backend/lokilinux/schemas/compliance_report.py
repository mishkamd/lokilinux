"""
LokiLinux — Reporting Engine Pydantic schemas.
"""

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel

from lokilinux.schemas.common import CursorPage


class ReportType(str, Enum):
    FLEET_SUMMARY = "FLEET_SUMMARY"
    POLICY_SET = "POLICY_SET"
    DATACENTER = "DATACENTER"
    CUSTOM = "CUSTOM"
    FRAMEWORK = "FRAMEWORK"
    EXCEPTION = "EXCEPTION"
    EXECUTIVE_SUMMARY = "EXECUTIVE_SUMMARY"


class ReportFormat(str, Enum):
    JSON = "JSON"
    CSV = "CSV"
    XLSX = "XLSX"
    PDF = "PDF"


class ComplianceReportCreate(BaseModel):
    report_type: ReportType
    format: ReportFormat
    params: dict = {}


class ComplianceReportResponse(BaseModel):
    id: UUID
    report_type: ReportType
    format: ReportFormat
    params: dict
    status: str
    artifact_uri: str | None = None
    storage_object_id: UUID | None = None
    error_message: str | None = None
    generated_by: UUID | None = None
    created_at: datetime
    completed_at: datetime | None = None

    model_config = {"from_attributes": True}


ComplianceReportListResponse = CursorPage[ComplianceReportResponse]
