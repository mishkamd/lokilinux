"""
LokiLinux — Inventory Collector Pydantic schemas.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from lokilinux.schemas.common import CursorPage


class InventorySnapshotResponse(BaseModel):
    id: UUID
    agent_id: UUID
    domain: str
    content_hash: str
    taken_at: datetime
    facts: dict | None = None  # decoded inventory_blobs.body; None if the blob is missing/undecodable

    model_config = {"from_attributes": True}


class InventoryDeltaResponse(BaseModel):
    time: datetime
    agent_id: UUID
    domain: str
    prev_hash: str | None = None
    new_hash: str
    diff: dict | None = None

    model_config = {"from_attributes": True}


InventoryDeltaListResponse = CursorPage[InventoryDeltaResponse]
