"""
LokiLinux — Category/Project Pydantic schemas.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class CategoryCreate(BaseModel):
    name: str


class CategoryResponse(BaseModel):
    id: UUID
    name: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ProjectCreate(BaseModel):
    name: str
    category_id: UUID | None = None


class ProjectResponse(BaseModel):
    id: UUID
    name: str
    category_id: UUID | None = None
    created_at: datetime

    model_config = {"from_attributes": True}
