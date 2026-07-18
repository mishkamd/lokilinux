"""
LokiLinux — Servers/Agents router.

GET  /servers             — cursor-paginated list, filters: status, search
GET  /servers/{id}        — detail with Redis cache (TTL_SERVER_LIST)
GET  /servers/{id}/packages — installed package inventory (from heartbeat sync)
GET  /servers/{id}/metrics — latest health snapshot (cpu/memory/disk %, from heartbeat)
POST /servers/{id}/maintenance — toggle maintenance mode
PATCH /servers/{id}/assignment — set category/project
"""

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.api.v1.routers._common import parse_agent_pk
from lokilinux.auth.dependencies import get_current_user, require_role
from lokilinux.cache import RedisCache, TTL_SERVER_LIST
from lokilinux.dependencies import get_cache, get_db
from lokilinux.models.agent import Agent, AgentHealth, AgentStatus
from lokilinux.models.cve import Package
from lokilinux.schemas.common import CursorPage, decode_cursor, encode_cursor
from lokilinux.schemas.cve import PackageResponse
from lokilinux.schemas.server import AgentAssignmentUpdate, AgentHealthResponse, AgentResponse

router = APIRouter()

# NOTE: named TTL_SERVER_LIST but reused here for server DETAIL (86400s = 1 day).
# The list endpoint below uses a separate hardcoded ttl=30 instead. Looks inverted
# for an actively-viewed detail page — flagged during audit, not changed (behavior
# change, needs a decision on intended cache semantics before touching).
_DETAIL_TTL = TTL_SERVER_LIST  # 86400s


# ── List servers ──────────────────────────────────────────────────────────────

@router.get("", response_model=CursorPage[AgentResponse])
async def list_servers(
    cursor: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    status: AgentStatus | None = Query(None),
    search: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    cache: RedisCache = Depends(get_cache),
    _: dict = Depends(get_current_user),
) -> CursorPage[AgentResponse]:
    cache_key = f"server:list:{status}:{search}:{cursor}:{limit}"
    if hit := await cache.get_cached(cache_key):
        return CursorPage[AgentResponse].model_validate(hit)

    q = select(Agent).order_by(Agent.created_at.desc(), Agent.id.desc())

    if status:
        q = q.where(Agent.status == status.value)
    if search:
        q = q.where(or_(
            Agent.hostname.ilike(f"%{search}%"),
            Agent.os_distro.ilike(f"%{search}%"),
        ))

    if cursor:
        raw = decode_cursor(cursor)
        # cursor encodes "created_at_iso:uuid"
        try:
            ts_str, uid = raw.rsplit(":", 1)
        except ValueError:
            raise HTTPException(status_code=400, detail="Malformed cursor")
        from datetime import datetime
        from uuid import UUID
        ts = datetime.fromisoformat(ts_str)
        q = q.where(
            (Agent.created_at < ts)
            | ((Agent.created_at == ts) & (Agent.id < UUID(uid)))
        )

    q = q.limit(limit + 1)
    rows = (await db.execute(q)).scalars().all()

    has_more = len(rows) > limit
    items = rows[:limit]
    next_cursor: str | None = None
    if has_more and items:
        last = items[-1]
        next_cursor = encode_cursor(f"{last.created_at.isoformat()}:{last.id}")

    # total count (no cursor filter — lightweight approximate)
    count_q = select(func.count()).select_from(Agent)
    if status:
        count_q = count_q.where(Agent.status == status.value)
    total = (await db.execute(count_q)).scalar()

    page = CursorPage[AgentResponse](
        items=[AgentResponse.model_validate(a) for a in items],
        next_cursor=next_cursor,
        total=total,
    )
    await cache.set_cached(cache_key, json.loads(page.model_dump_json()), ttl=30)
    return page


# ── Server detail ─────────────────────────────────────────────────────────────

@router.get("/{agent_id}", response_model=AgentResponse)
async def get_server(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    cache: RedisCache = Depends(get_cache),
    _: dict = Depends(get_current_user),
) -> AgentResponse:
    cache_key = f"agent:{agent_id}:detail"
    if hit := await cache.get_cached(cache_key):
        return AgentResponse.model_validate(hit)

    pk = parse_agent_pk(agent_id)
    row = (await db.execute(
        select(Agent).where(Agent.id == pk)
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Server not found")

    resp = AgentResponse.model_validate(row)
    await cache.set_cached(cache_key, json.loads(resp.model_dump_json()), ttl=_DETAIL_TTL)
    return resp


# ── Package inventory ─────────────────────────────────────────────────────────

@router.get("/{agent_id}/packages", response_model=list[PackageResponse])
async def list_server_packages(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
) -> list[PackageResponse]:
    pk = parse_agent_pk(agent_id)
    exists = (await db.execute(select(Agent.id).where(Agent.id == pk))).scalar_one_or_none()
    if exists is None:
        raise HTTPException(status_code=404, detail="Server not found")

    rows = (await db.execute(
        select(Package).where(Package.agent_id == pk).order_by(Package.name)
    )).scalars().all()
    return [PackageResponse.model_validate(p) for p in rows]


# ── Metrics snapshot ──────────────────────────────────────────────────────────

_METRICS_TTL = 30  # live data — short cache


@router.get("/{agent_id}/metrics", response_model=AgentHealthResponse | None)
async def get_latest_metrics(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    cache: RedisCache = Depends(get_cache),
    _: dict = Depends(get_current_user),
) -> AgentHealthResponse | None:
    """Get latest health snapshot (cpu/memory/disk %) for a server."""
    cache_key = f"agent:{agent_id}:metrics"
    hit = await cache.get_cached(cache_key)
    if hit is not None:
        return AgentHealthResponse.model_validate(hit) if hit else None

    pk = parse_agent_pk(agent_id)

    agent = (await db.execute(select(Agent).where(Agent.id == pk))).scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=404, detail="Server not found")

    row = (await db.execute(
        select(AgentHealth)
        .where(AgentHealth.agent_id == pk)
        .order_by(desc(AgentHealth.recorded_at))
        .limit(1)
    )).scalar_one_or_none()

    if row is None:
        await cache.set_cached(cache_key, None, ttl=_METRICS_TTL)
        return None

    resp = AgentHealthResponse(
        agent_id=agent.agent_id,
        status=agent.status.value if hasattr(agent.status, "value") else str(agent.status),
        cpu_usage=row.cpu_usage,
        cpu_count=row.cpu_count,
        memory_usage=row.memory_usage,
        memory_total_bytes=row.memory_total_bytes,
        memory_used_bytes=row.memory_used_bytes,
        disk_usage=row.disk_usage,
        disk_total_bytes=row.disk_total_bytes,
        disk_used_bytes=row.disk_used_bytes,
        swap_usage=row.swap_usage,
        swap_total_bytes=row.swap_total_bytes,
        swap_used_bytes=row.swap_used_bytes,
        network_latency_ms=row.network_latency_ms,
        connection_failures=row.connection_failures,
        recorded_at=row.recorded_at,
    )
    await cache.set_cached(cache_key, resp.model_dump(mode="json"), ttl=_METRICS_TTL)
    return resp


# ── Maintenance toggle ────────────────────────────────────────────────────────

@router.post("/{agent_id}/maintenance", response_model=AgentResponse)
async def set_maintenance(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    cache: RedisCache = Depends(get_cache),
    _: dict = Depends(get_current_user),
) -> AgentResponse:
    pk = parse_agent_pk(agent_id)
    row = (await db.execute(
        select(Agent).where(Agent.id == pk)
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Server not found")

    row.status = (
        AgentStatus.ACTIVE
        if row.status == AgentStatus.MAINTENANCE
        else AgentStatus.MAINTENANCE
    )
    await db.flush()
    await cache.invalidate_agent(agent_id)

    return AgentResponse.model_validate(row)


# ── Category/Project assignment ───────────────────────────────────────────────

@router.patch("/{agent_id}/assignment", response_model=AgentResponse)
async def set_assignment(
    agent_id: str,
    body: AgentAssignmentUpdate,
    db: AsyncSession = Depends(get_db),
    cache: RedisCache = Depends(get_cache),
    _: dict = Depends(require_role("ADMIN", "OPERATOR")),
) -> AgentResponse:
    pk = parse_agent_pk(agent_id)
    row = (await db.execute(select(Agent).where(Agent.id == pk))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Server not found")

    row.category_id = body.category_id
    row.project_id = body.project_id
    await db.flush()
    await cache.invalidate_agent(agent_id)

    return AgentResponse.model_validate(row)
