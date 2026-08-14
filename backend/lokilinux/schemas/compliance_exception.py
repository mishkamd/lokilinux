"""
LokiLinux — Compliance exceptions/waivers Pydantic schemas.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class ExceptionCreate(BaseModel):
    rule_id: UUID
    agent_id: UUID | None = None
    scope_selector: dict[str, Any] = Field(default_factory=dict)
    reason: str
    owner: str
    expires_at: datetime


class ExceptionResponse(BaseModel):
    id: UUID
    rule_id: UUID
    rule_key: str | None = None
    rule_title: str | None = None
    agent_id: UUID | None = None
    hostname: str | None = None
    scope_selector: dict[str, Any] = Field(default_factory=dict)
    reason: str
    owner: str
    requested_by: UUID | None = None
    approved_by: UUID | None = None
    approved_at: datetime | None = None
    status: str
    expires_at: datetime
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
