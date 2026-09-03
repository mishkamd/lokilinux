"""
LokiLinux — Object storage Pydantic schemas.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from lokilinux.schemas.common import CursorPage


class StorageObjectResponse(BaseModel):
    id: UUID
    filename: str
    original_filename: str
    content_type: str
    size_bytes: int
    sha256: str
    storage_provider: str
    bucket: str
    object_key: str
    version: int
    category: str
    status: str
    created_by: UUID | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


StorageObjectListResponse = CursorPage[StorageObjectResponse]


class ImportUrlRequest(BaseModel):
    url: str
    category: str
    original_filename: str | None = None


class VerifyResponse(BaseModel):
    object_id: UUID
    sha256_recorded: str
    sha256_match: bool


class PresignResponse(BaseModel):
    url: str
    expires_in: int
