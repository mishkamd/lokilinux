"""
LokiLinux — Job Template Pydantic schemas (AWX "Job Template" equivalent).
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from lokilinux.schemas.job import JobResponse


class PlaybookTemplateBase(BaseModel):
    name: str
    description: str | None = None
    playbook_id: UUID
    agent_ids: list[UUID]
    extra_vars: dict | None = None


class PlaybookTemplateCreate(PlaybookTemplateBase):
    pass


class PlaybookTemplateUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    agent_ids: list[UUID] | None = None
    extra_vars: dict | None = None


class PlaybookTemplateResponse(PlaybookTemplateBase):
    id: UUID
    created_by: UUID | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PlaybookTemplateLaunchRequest(BaseModel):
    agent_ids: list[UUID] | None = None  # override; None = use template's saved agent_ids
    extra_vars: dict | None = None  # merged over template's saved extra_vars


PlaybookTemplateLaunchResponse = JobResponse
