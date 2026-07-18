"""
LokiLinux — Agent ORM models.

Column names are the contract with existing routers/schemas — do not rename.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, String, text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from lokilinux.db import Base


class AgentStatus(enum.Enum):
    PENDING = "PENDING"
    REGISTERED = "REGISTERED"
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    UNHEALTHY = "UNHEALTHY"
    MAINTENANCE = "MAINTENANCE"


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    agent_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)

    # Status & registration
    status: Mapped[AgentStatus] = mapped_column(SAEnum(AgentStatus, name="agentstatus"), default=AgentStatus.PENDING, nullable=False)
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), nullable=False)
    last_heartbeat: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_heartbeat_ip: Mapped[str | None] = mapped_column(String(45))

    # Certificate / mTLS
    cert_fingerprint: Mapped[str | None] = mapped_column(String(64), unique=True)
    cert_valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cert_valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Versions
    agent_version: Mapped[str | None] = mapped_column(String(50))
    platform_version: Mapped[str | None] = mapped_column(String(50))

    # Server identity — names match AgentResponse schema fields
    hostname: Mapped[str | None] = mapped_column(String(255))
    fqdn: Mapped[str | None] = mapped_column(String(255))
    os_family: Mapped[str | None] = mapped_column(String(50))
    os_distro: Mapped[str | None] = mapped_column(String(100))
    os_version: Mapped[str | None] = mapped_column(String(50))
    kernel_version: Mapped[str | None] = mapped_column(String(100))
    arch: Mapped[str | None] = mapped_column(String(50))

    # Reported by heartbeat — local OS accounts (UID >= 1000) and recent agent log lines
    system_users: Mapped[list | None] = mapped_column(JSONB)
    recent_logs: Mapped[list | None] = mapped_column(JSONB)

    # Reported by heartbeat — full mount list (df-style), network interfaces
    # (ip-a-style), and block device tree (lsblk-style). Snapshot only —
    # overwritten each heartbeat, no history kept.
    disks: Mapped[list | None] = mapped_column(JSONB)
    network_interfaces: Mapped[list | None] = mapped_column(JSONB)
    block_devices: Mapped[list | None] = mapped_column(JSONB)
    listening_ports: Mapped[list | None] = mapped_column(JSONB)

    # SHA256 of the last package list synced — lets heartbeat skip the upsert
    # entirely when unchanged since the previous heartbeat.
    last_packages_checksum: Mapped[str | None] = mapped_column(String(64))

    # Organization
    tags: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    custom_facts: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))

    category_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("categories.id", ondelete="SET NULL"))
    project_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"))

    # Active policy (nullable FK — policies created first)
    current_policy_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("policies.id", use_alter=True, name="fk_agent_current_policy"))
    plugin_policy_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("policies.id", use_alter=True, name="fk_agent_plugin_policy"))

    # Denormalized counters for fast dashboard reads
    cve_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cve_last_scan: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updates_available: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), nullable=False)

    # Read-only aliases so AgentResponse can expose friendlier field names
    # without renaming the underlying columns (which are the DB contract).
    @property
    def ip_address(self) -> str | None:
        return self.last_heartbeat_ip

    @property
    def os_name(self) -> str | None:
        return self.os_distro

    @property
    def last_seen_at(self) -> datetime | None:
        return self.last_heartbeat


class AgentHealth(Base):
    """Periodic health snapshots — regular table (not a hypertable)."""

    __tablename__ = "agent_health"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True)

    cpu_usage: Mapped[float | None] = mapped_column(Float)
    cpu_count: Mapped[int | None] = mapped_column(Integer)
    memory_usage: Mapped[float | None] = mapped_column(Float)
    memory_total_bytes: Mapped[int | None] = mapped_column(BigInteger)
    memory_used_bytes: Mapped[int | None] = mapped_column(BigInteger)
    disk_usage: Mapped[float | None] = mapped_column(Float)
    disk_total_bytes: Mapped[int | None] = mapped_column(BigInteger)
    disk_used_bytes: Mapped[int | None] = mapped_column(BigInteger)
    swap_usage: Mapped[float | None] = mapped_column(Float)
    swap_total_bytes: Mapped[int | None] = mapped_column(BigInteger)
    swap_used_bytes: Mapped[int | None] = mapped_column(BigInteger)
    network_latency_ms: Mapped[float | None] = mapped_column(Float)
    is_disk_full: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_memory_critical: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    connection_failures: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), nullable=False, index=True)


class AgentMetrics(Base):
    """Time-series metrics — TimescaleDB hypertable on 'time'."""

    __tablename__ = "agent_metrics"

    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, primary_key=True)
    agent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, primary_key=True)

    # CPU
    cpu_user: Mapped[float | None] = mapped_column(Float)
    cpu_system: Mapped[float | None] = mapped_column(Float)
    cpu_idle: Mapped[float | None] = mapped_column(Float)
    cpu_count: Mapped[int | None] = mapped_column(Integer)

    # Memory
    memory_total: Mapped[int | None] = mapped_column(Integer)
    memory_used: Mapped[int | None] = mapped_column(Integer)
    memory_available: Mapped[int | None] = mapped_column(Integer)

    # Disk
    disk_total: Mapped[int | None] = mapped_column(Integer)
    disk_used: Mapped[int | None] = mapped_column(Integer)
    disk_io_read_bytes: Mapped[int | None] = mapped_column(Integer)
    disk_io_write_bytes: Mapped[int | None] = mapped_column(Integer)

    # Network
    network_bytes_in: Mapped[int | None] = mapped_column(Integer)
    network_bytes_out: Mapped[int | None] = mapped_column(Integer)
    network_packets_in: Mapped[int | None] = mapped_column(Integer)
    network_packets_out: Mapped[int | None] = mapped_column(Integer)

    # Processes
    process_count: Mapped[int | None] = mapped_column(Integer)
    thread_count: Mapped[int | None] = mapped_column(Integer)

    tags: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
