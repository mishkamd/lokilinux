"""
LokiLinux — Ansible Playbook Pydantic schemas.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from lokilinux.schemas.job import JobResponse


class PlaybookCreate(BaseModel):
    name: str
    description: str | None = None
    content: str
    default_extra_vars: dict | None = None
    role_ids: list[UUID] = []
    project_id: UUID | None = None


class PlaybookUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    content: str | None = None
    default_extra_vars: dict | None = None
    is_enabled: bool | None = None
    role_ids: list[UUID] | None = None
    project_id: UUID | None = None


class PlaybookResponse(BaseModel):
    """Full detail — GET/POST/PATCH single-item responses. `content` is
    resolved explicitly by the router (legacy column or object storage), so
    this is never built via `.model_validate(playbook)` alone."""

    id: UUID
    name: str
    description: str | None = None
    content: str
    default_extra_vars: dict | None = None
    role_ids: list[UUID] = []
    project_id: UUID | None = None
    version: int
    is_enabled: bool
    generated_by: str | None = None
    created_by: UUID | None = None
    created_at: datetime
    updated_at: datetime


class PlaybookListItem(BaseModel):
    """List endpoint response — omits `content` so listing playbooks never
    triggers an object-storage read per row (see PlaybookService.list_playbooks
    / routers/playbooks.py)."""

    id: UUID
    name: str
    description: str | None = None
    default_extra_vars: dict | None = None
    role_ids: list[UUID] = []
    project_id: UUID | None = None
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
