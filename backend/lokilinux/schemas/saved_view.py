"""LokiLinux — Saved view schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class SavedViewCreate(BaseModel):
    scope: str = Field(max_length=100)
    name: str = Field(max_length=100)
    path: str = Field(max_length=255)
    query: dict[str, str] = Field(default_factory=dict)


class SavedViewResponse(BaseModel):
    id: UUID
    scope: str
    name: str
    path: str
    query: dict[str, str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
