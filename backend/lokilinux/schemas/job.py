"""
LokiLinux — Job Pydantic schemas.
"""

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel

from lokilinux.schemas.common import CursorPage


class JobStatus(str, Enum):
    QUEUED = "QUEUED"
    SCHEDULED = "SCHEDULED"
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"
    CANCELLED = "CANCELLED"


class JobType(str, Enum):
    PACKAGE_UPDATE = "PACKAGE_UPDATE"
    SECURITY_PATCH = "SECURITY_PATCH"
    INVENTORY_SCAN = "INVENTORY_SCAN"
    CVE_SCAN = "CVE_SCAN"
    CUSTOM_COMMAND = "CUSTOM_COMMAND"
    REMEDIATION = "REMEDIATION"
    ANSIBLE_PLAYBOOK = "ANSIBLE_PLAYBOOK"


class JobBase(BaseModel):
    name: str
    job_type: JobType
    description: str | None = None


class JobCreate(JobBase):
    target_servers: dict  # {agent_ids: [...]} or {filters: {...}}
    parameters: dict | None = None
    scheduled_time: datetime | None = None
    policy_id: UUID | None = None


class JobResponse(JobBase):
    id: UUID
    status: JobStatus
    target_servers: dict
    parameters: dict | None = None
    scheduled_time: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    dedup_key: str | None = None
    requires_approval: bool = False
    approved_by: UUID | None = None
    approved_at: datetime | None = None
    created_by: UUID | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class JobResultResponse(BaseModel):
    agent_id: UUID
    hostname: str | None = None
    status: str
    exit_code: int | None = None
    error_message: str | None = None
    stdout: str | None = None
    stderr: str | None = None
    duration_seconds: int | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


JobListResponse = CursorPage[JobResponse]
