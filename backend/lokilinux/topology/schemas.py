"""
LokiLinux — Topology Pydantic schemas.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class TopologyNodeCreate(BaseModel):
    model_config = {"extra": "forbid"}

    kind: str  # HOST|SERVICE|APPLICATION|EXTERNAL
    name: str
    agent_id: UUID | None = None


class TopologyNodeResponse(BaseModel):
    id: UUID
    tenant_id: str
    kind: str
    name: str
    agent_id: UUID | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class TopologyEdgeCreate(BaseModel):
    model_config = {"extra": "forbid"}

    from_node: UUID
    to_node: UUID
    kind: str = "DEPENDS_ON"


class TopologyEdgeResponse(BaseModel):
    from_node: UUID
    to_node: UUID
    kind: str

    model_config = {"from_attributes": True}


class TopologyGraphResponse(BaseModel):
    nodes: list[TopologyNodeResponse]
    edges: list[TopologyEdgeResponse]
