"""
LokiLinux — Plugin ORM models.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from lokilinux.db import Base


class PluginStatus(enum.Enum):
    PENDING_INSTALL = "PENDING_INSTALL"
    INSTALLING = "INSTALLING"
    INSTALLED = "INSTALLED"
    INSTALLING_FAILED = "INSTALLING_FAILED"
    ENABLED = "ENABLED"
    DISABLED = "DISABLED"
    ERROR = "ERROR"


class Plugin(Base):
    __tablename__ = "plugins"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255))
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    author: Mapped[str | None] = mapped_column(String(255))
    icon_url: Mapped[str | None] = mapped_column(String(512))
    documentation_url: Mapped[str | None] = mapped_column(String(512))

    # Type & compatibility
    plugin_type: Mapped[str] = mapped_column(String(50), nullable=False)  # control-plane / agent / ui / notification
    min_platform_version: Mapped[str | None] = mapped_column(String(50))
    max_platform_version: Mapped[str | None] = mapped_column(String(50))

    # Source & integrity
    source_url: Mapped[str | None] = mapped_column(String(512))
    manifest: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    checksum: Mapped[str | None] = mapped_column(String(64))

    # Status
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_installed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    installation_status: Mapped[PluginStatus] = mapped_column(SAEnum(PluginStatus, name="pluginstatus"), default=PluginStatus.PENDING_INSTALL, nullable=False)

    # Configuration
    configuration: Mapped[dict | None] = mapped_column(JSONB)
    config_schema: Mapped[dict | None] = mapped_column(JSONB)
    required_permissions: Mapped[list | None] = mapped_column(JSONB)

    # Versioning / marketplace
    is_latest: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    security_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    download_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rating: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    installed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_enabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), nullable=False)


class PluginInstallation(Base):
    """Per-agent plugin installation record. agent_id is NULL for global installs."""

    __tablename__ = "plugin_installations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    plugin_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("plugins.id", ondelete="CASCADE"), nullable=False, index=True)
    agent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), index=True)

    status: Mapped[str | None] = mapped_column(String(50))  # PENDING / INSTALLED / ENABLED / DISABLED / ERROR
    error_message: Mapped[str | None] = mapped_column(Text)
    local_config: Mapped[dict | None] = mapped_column(JSONB)
    installed_version: Mapped[str | None] = mapped_column(String(50))

    installed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    enabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), nullable=False)
