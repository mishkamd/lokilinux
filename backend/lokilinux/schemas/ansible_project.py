"""
LokiLinux — Ansible Project Pydantic schemas.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class AnsibleProjectBase(BaseModel):
    name: str
    description: str | None = None
    default_agent_ids: list[UUID] = []


class AnsibleProjectCreate(AnsibleProjectBase):
    pass


class AnsibleProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    default_agent_ids: list[UUID] | None = None


class AnsibleProjectResponse(AnsibleProjectBase):
    id: UUID
    created_by: UUID | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
