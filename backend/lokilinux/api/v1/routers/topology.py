"""
LokiLinux — Topology router: dependency graph CRUD + read.

Mutations are ADMIN/OPERATOR only — the graph feeds correlation candidate
enrichment (Task C1) and incident evidence, wrong edges misdirect
root-cause reasoning for everyone, not just the editor.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.auth.dependencies import get_current_user, require_role
from lokilinux.dependencies import get_db
from lokilinux.topology.models import TopologyEdge, TopologyNode
from lokilinux.topology.schemas import (
    TopologyEdgeCreate,
    TopologyGraphResponse,
    TopologyNodeCreate,
    TopologyNodeResponse,
)
from lokilinux.topology.service import add_edge, remove_edge

router = APIRouter()

_TENANT_ID = "default"


@router.get("", response_model=TopologyGraphResponse)
async def get_graph(
    db: AsyncSession = Depends(get_db),
    _: dict[str, Any] = Depends(get_current_user),
) -> TopologyGraphResponse:
    nodes = (await db.execute(select(TopologyNode).where(TopologyNode.tenant_id == _TENANT_ID))).scalars().all()
    edges = (await db.execute(select(TopologyEdge))).scalars().all()
    return TopologyGraphResponse.model_validate({"nodes": nodes, "edges": edges})


@router.post("/nodes", response_model=TopologyNodeResponse, status_code=201)
async def create_node(
    payload: TopologyNodeCreate,
    db: AsyncSession = Depends(get_db),
    _: dict[str, Any] = Depends(require_role("ADMIN", "OPERATOR")),
) -> TopologyNode:
    node = TopologyNode(tenant_id=_TENANT_ID, kind=payload.kind, name=payload.name, agent_id=payload.agent_id)
    db.add(node)
    await db.flush()
    return node


@router.post("/edges", status_code=201)
async def create_edge(
    payload: TopologyEdgeCreate,
    db: AsyncSession = Depends(get_db),
    _: dict[str, Any] = Depends(require_role("ADMIN", "OPERATOR")),
) -> dict[str, str]:
    await add_edge(db, payload.from_node, payload.to_node, payload.kind)
    return {"status": "created"}


@router.delete("/edges", status_code=204)
async def delete_edge(
    from_node: UUID,
    to_node: UUID,
    db: AsyncSession = Depends(get_db),
    _: dict[str, Any] = Depends(require_role("ADMIN", "OPERATOR")),
) -> None:
    await remove_edge(db, from_node, to_node)
