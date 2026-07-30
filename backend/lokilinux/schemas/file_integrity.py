"""
LokiLinux — File Integrity Monitoring Pydantic schemas.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

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
    path: str
    old_hash: str | None = None
    new_hash: str | None = None
    change_kind: str

    model_config = {"from_attributes": True}


FileChangeListResponse = CursorPage[FileChangeResponse]
