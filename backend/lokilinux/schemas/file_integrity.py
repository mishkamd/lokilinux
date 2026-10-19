"""
LokiLinux — File Integrity Monitoring Pydantic schemas.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from lokilinux.schemas.common import CursorPage


class FileHashResponse(BaseModel):
    agent_id: UUID
    path: str
    algo: str
    hash: str
    mode: int | None = None
    uid: int | None = None
    gid: int | None = None
    size_bytes: int | None = None
    mtime: datetime | None = None
    updated_at: datetime

    model_config = {"from_attributes": True}


class FileChangeResponse(BaseModel):
    time: datetime
    agent_id: UUID
    hostname: str | None = None
    path: str
    old_hash: str | None = None
    new_hash: str | None = None
    change_kind: str
    old_mode: int | None = None
    new_mode: int | None = None
    old_uid: int | None = None
    new_uid: int | None = None
    old_gid: int | None = None
    new_gid: int | None = None

    model_config = {"from_attributes": True}


FileChangeListResponse = CursorPage[FileChangeResponse]


class FIMScopeResponse(BaseModel):
    scope_type: str
    agent_id: UUID | None = None
    watch_paths: list[str]
    ignore_paths: list[str]
    updated_at: datetime
    updated_by: UUID | None = None

    model_config = {"from_attributes": True}


class FIMAgentScopeResponse(FIMScopeResponse):
    hostname: str | None = None


class FIMScopesOverview(BaseModel):
    global_scope: FIMScopeResponse
    agents: list[FIMAgentScopeResponse]


class FIMScopeUpdate(BaseModel):
    watch_paths: list[str] = Field(..., max_length=64)
    ignore_paths: list[str] = Field(default_factory=list, max_length=64)
