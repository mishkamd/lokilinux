"""
LokiLinux — Agent/Server Pydantic schemas.
"""

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel

from lokilinux.schemas.common import CursorPage


class AgentStatus(str, Enum):
    PENDING = "PENDING"
    REGISTERED = "REGISTERED"
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    UNHEALTHY = "UNHEALTHY"
    MAINTENANCE = "MAINTENANCE"


class AgentBase(BaseModel):
    hostname: str | None = None
    fqdn: str | None = None
    os_distro: str | None = None
    os_version: str | None = None
    kernel_version: str | None = None
    arch: str | None = None
    tags: dict | None = None
    system_users: list[str] | None = None
    recent_logs: dict | None = None
    disks: list[dict] | None = None
    network_interfaces: list[dict] | None = None
    block_devices: list[dict] | None = None
    listening_ports: list[dict] | None = None
    category_id: UUID | None = None
    project_id: UUID | None = None
    agent_group_id: UUID | None = None


class AgentCreate(AgentBase):
    agent_id: str
    cert_fingerprint: str | None = None


class AgentAssignmentUpdate(BaseModel):
    category_id: UUID | None = None
    project_id: UUID | None = None
    agent_group_id: UUID | None = None


class AgentResponse(AgentBase):
    id: UUID
    agent_id: str
    status: AgentStatus
    last_heartbeat: datetime | None = None
    last_seen_at: datetime | None = None
    ip_address: str | None = None
    os_name: str | None = None
    cve_count: int = 0
    updates_available: int = 0
    agent_version: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


AgentListResponse = CursorPage[AgentResponse]


class AgentHealthResponse(BaseModel):
    agent_id: str
    status: str
    cpu_usage: float | None = None
    cpu_count: int | None = None
    memory_usage: float | None = None
    memory_total_bytes: int | None = None
    memory_used_bytes: int | None = None
    disk_usage: float | None = None
    disk_total_bytes: int | None = None
    disk_used_bytes: int | None = None
    swap_usage: float | None = None
    swap_total_bytes: int | None = None
    swap_used_bytes: int | None = None
    network_latency_ms: float | None = None
    connection_failures: int = 0
    recorded_at: datetime | None = None

    model_config = {"from_attributes": True}
