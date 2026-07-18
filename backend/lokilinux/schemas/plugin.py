"""
LokiLinux — Plugin Pydantic schemas.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from lokilinux.models.plugin import PluginStatus


class PluginResponse(BaseModel):
    id: UUID
    name: str
    display_name: str | None = None
    version: str
    description: str | None = None
    author: str | None = None
    icon_url: str | None = None
    plugin_type: str
    installation_status: PluginStatus
    is_enabled: bool
    is_installed: bool
    security_verified: bool
    download_count: int
    rating: float
    installed_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class PluginInstallationResponse(BaseModel):
    id: int
    plugin_id: UUID
    agent_id: UUID | None = None
    status: str | None = None
    installed_version: str | None = None
    installed_at: datetime | None = None

    model_config = {"from_attributes": True}
