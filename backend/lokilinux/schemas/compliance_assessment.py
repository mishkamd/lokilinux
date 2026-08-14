"""
LokiLinux — Async fleet assessment Pydantic schemas (docs/compliance §24).
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class AssessmentCreate(BaseModel):
    policy_set_id: UUID
    scope_selector: dict[str, Any] = Field(default_factory=dict)


class AssessmentResponse(BaseModel):
    id: UUID
    scope_selector: dict[str, Any] = Field(default_factory=dict)
    policy_set_id: UUID | None = None
    status: str
    servers_total: int
    servers_done: int
    rules_total: int
    rules_done: int
    created_by: UUID | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None

    model_config = {"from_attributes": True}
