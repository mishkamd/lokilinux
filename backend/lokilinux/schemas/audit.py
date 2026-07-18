"""
LokiLinux — Audit log Pydantic schemas.
"""

from datetime import datetime

from pydantic import BaseModel


class AuditLogResponse(BaseModel):
    id: int
    timestamp: datetime
    actor_name: str | None = None
    action: str
    resource_type: str | None = None
    resource_id: str | None = None
    status: str | None = None

    model_config = {"from_attributes": True}
