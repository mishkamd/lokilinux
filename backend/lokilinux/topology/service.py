"""
LokiLinux — topology service: node/edge CRUD + recursive dependency resolver.

upstream(node) = the dependency closure — everything this node depends ON,
following edges from_node -> to_node outward from the start.
downstream(node) = the impact set — everything that depends ON this node,
following edges backward (to_node -> from_node) from the start.

Depth capped at 5 (plan): enough for any realistic dependency chain in this
system, and bounds a pathological cycle from turning into an unbounded scan
(the recursive CTE has no other cycle guard).
"""

from typing import Any
from uuid import UUID

from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.topology.models import TopologyEdge, TopologyNode

MAX_DEPTH = 5
_TENANT_ID = "default"

_UPSTREAM_CTE_SQL = """
WITH RECURSIVE closure(node_id, depth) AS (
    SELECT CAST(:start_id AS uuid), 0
    UNION ALL
    SELECT e.to_node, c.depth + 1
    FROM topology_edges e
    JOIN closure c ON e.from_node = c.node_id
    WHERE c.depth < :max_depth
)
SELECT DISTINCT n.id, n.name, n.kind
FROM closure c
JOIN topology_nodes n ON n.id = c.node_id
WHERE c.node_id != CAST(:start_id AS uuid)
"""

_DOWNSTREAM_CTE_SQL = """
WITH RECURSIVE closure(node_id, depth) AS (
    SELECT CAST(:start_id AS uuid), 0
    UNION ALL
    SELECT e.from_node, c.depth + 1
    FROM topology_edges e
    JOIN closure c ON e.to_node = c.node_id
    WHERE c.depth < :max_depth
)
SELECT DISTINCT n.id, n.name, n.kind
FROM closure c
JOIN topology_nodes n ON n.id = c.node_id
WHERE c.node_id != CAST(:start_id AS uuid)
"""


async def ensure_host_node(
    db: AsyncSession, *, agent_id: UUID, hostname: str, tenant_id: str = _TENANT_ID
) -> TopologyNode:
    """Idempotent — called from the signal_processor hook on host.heartbeat.ok."""
    stmt = (
        pg_insert(TopologyNode)
        .values(tenant_id=tenant_id, kind="HOST", name=hostname, agent_id=agent_id)
        .on_conflict_do_nothing(index_elements=["tenant_id", "kind", "name"])
        .returning(TopologyNode)
    )
    row = (await db.execute(stmt)).scalar_one_or_none()
    await db.commit()
    if row is not None:
        return row
    return (
        await db.execute(
            select(TopologyNode).where(
                TopologyNode.tenant_id == tenant_id, TopologyNode.kind == "HOST", TopologyNode.name == hostname
            )
        )
    ).scalar_one()


async def add_edge(db: AsyncSession, from_node: UUID, to_node: UUID, kind: str = "DEPENDS_ON") -> None:
    stmt = (
        pg_insert(TopologyEdge)
        .values(from_node=from_node, to_node=to_node, kind=kind)
        .on_conflict_do_nothing(index_elements=["from_node", "to_node"])
    )
    await db.execute(stmt)
    await db.commit()


async def remove_edge(db: AsyncSession, from_node: UUID, to_node: UUID) -> None:
    await db.execute(delete(TopologyEdge).where(TopologyEdge.from_node == from_node, TopologyEdge.to_node == to_node))
    await db.commit()


async def upstream(db: AsyncSession, node_id: UUID, *, max_depth: int = MAX_DEPTH) -> list[dict[str, Any]]:
    rows = (
        await db.execute(text(_UPSTREAM_CTE_SQL), {"start_id": str(node_id), "max_depth": max_depth})
    ).mappings().all()
    return [dict(r) for r in rows]


async def downstream(db: AsyncSession, node_id: UUID, *, max_depth: int = MAX_DEPTH) -> list[dict[str, Any]]:
    rows = (
        await db.execute(text(_DOWNSTREAM_CTE_SQL), {"start_id": str(node_id), "max_depth": max_depth})
    ).mappings().all()
    return [dict(r) for r in rows]
