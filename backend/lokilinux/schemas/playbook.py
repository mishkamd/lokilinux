"""
LokiLinux — Ansible Playbook Pydantic schemas.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from lokilinux.schemas.job import JobResponse


class PlaybookBase(BaseModel):
    name: str
    description: str | None = None
    content: str
    default_extra_vars: dict | None = None
    role_ids: list[UUID] = []
    project_id: UUID | None = None


class PlaybookCreate(PlaybookBase):
    pass


class PlaybookUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    content: str | None = None
    default_extra_vars: dict | None = None
    is_enabled: bool | None = None
    role_ids: list[UUID] | None = None
    project_id: UUID | None = None


class PlaybookResponse(PlaybookBase):
    id: UUID
    version: int
    is_enabled: bool
    generated_by: str | None = None
    created_by: UUID | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PlaybookExecuteRequest(BaseModel):
    agent_ids: list[UUID]
    extra_vars: dict | None = None


PlaybookExecuteResponse = JobResponse
