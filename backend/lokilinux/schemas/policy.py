"""
LokiLinux — Policy Pydantic schemas.
"""

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel

from lokilinux.schemas.common import CursorPage


class PolicyType(str, Enum):
    UPDATE = "UPDATE"
    SECURITY = "SECURITY"
    COMPLIANCE = "COMPLIANCE"
    MAINTENANCE = "MAINTENANCE"
    PLUGIN = "PLUGIN"


class PolicyBase(BaseModel):
    name: str
    description: str | None = None
    policy_type: PolicyType | None = None
    rules: dict
    target_servers: dict | None = None
    is_enabled: bool = True
    priority: int = 100


class PolicyCreate(PolicyBase):
    pass


class PolicyUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    rules: dict | None = None
    target_servers: dict | None = None
    is_enabled: bool | None = None
    priority: int | None = None


class PolicyResponse(PolicyBase):
    id: UUID
    version: int = 1
    created_by: UUID | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


PolicyListResponse = CursorPage[PolicyResponse]
