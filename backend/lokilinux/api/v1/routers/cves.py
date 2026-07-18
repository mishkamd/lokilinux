"""
LokiLinux — CVE / Vulnerability router.

GET /vulnerabilities                        — global list, filter: severity, agent_id
GET /vulnerabilities/{cve_id}               — CVE detail
GET /servers/{agent_id}/vulnerabilities     — per-server CVEs
"""

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.api.v1.routers._common import parse_agent_pk
from lokilinux.auth.dependencies import get_current_user
from lokilinux.cache import RedisCache, TTL_CVE_DATA
from lokilinux.dependencies import get_cache, get_db
from lokilinux.models.agent import Agent
from lokilinux.models.cve import AgentVulnerability, CVE
from lokilinux.schemas.common import CursorPage, decode_cursor, encode_cursor
from lokilinux.schemas.cve import CVEResponse, CVESeverity, VulnerabilityResponse

router = APIRouter()


# ── Global CVE list ───────────────────────────────────────────────────────────

@router.get("", response_model=CursorPage[CVEResponse])
async def list_vulnerabilities(
    cursor: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    severity: CVESeverity | None = Query(None),
    agent_id: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    cache: RedisCache = Depends(get_cache),
    _: dict = Depends(get_current_user),
) -> CursorPage[CVEResponse]:
    cache_key = f"cve:list:{severity}:{agent_id}:{cursor}:{limit}"
    if hit := await cache.get_cached(cache_key):
        return CursorPage[CVEResponse].model_validate(hit)

    q = select(CVE).order_by(CVE.cvss_v3_score.desc().nullslast(), CVE.id.desc())

    if severity:
        q = q.where(CVE.cvss_v3_severity == severity.value)
    if agent_id:
        # subquery: CVEs affecting this agent
        sub = select(AgentVulnerability.cve_id).join(
            Agent, Agent.id == AgentVulnerability.agent_id
        ).where(Agent.agent_id == agent_id)
        q = q.where(CVE.cve_id.in_(sub))

    if cursor:
        raw = decode_cursor(cursor)
        try:
            cve_id_str = raw  # cursor = str(db_id)
            cve_int = int(cve_id_str)
        except ValueError:
            raise HTTPException(status_code=400, detail="Malformed cursor")
        q = q.where(CVE.id < cve_int)

    q = q.limit(limit + 1)
    rows = (await db.execute(q)).scalars().all()

    has_more = len(rows) > limit
    items = rows[:limit]
    next_cursor = encode_cursor(str(items[-1].id)) if has_more and items else None

    page = CursorPage[CVEResponse](
        items=[CVEResponse.model_validate(c) for c in items],
        next_cursor=next_cursor,
    )
    await cache.set_cached(cache_key, json.loads(page.model_dump_json()), ttl=TTL_CVE_DATA)
    return page


# ── CVE detail ────────────────────────────────────────────────────────────────

@router.get("/{cve_id}", response_model=CVEResponse)
async def get_cve(
    cve_id: str,
    db: AsyncSession = Depends(get_db),
    cache: RedisCache = Depends(get_cache),
    _: dict = Depends(get_current_user),
) -> CVEResponse:
    cache_key = f"cve:{cve_id}:details"
    if hit := await cache.get_cached(cache_key):
        return CVEResponse.model_validate(hit)

    row = (await db.execute(select(CVE).where(CVE.cve_id == cve_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="CVE not found")

    resp = CVEResponse.model_validate(row)
    await cache.set_cached(cache_key, json.loads(resp.model_dump_json()), ttl=TTL_CVE_DATA)
    return resp


# ── Per-server CVEs ───────────────────────────────────────────────────────────

@router.get("/servers/{agent_id}", response_model=CursorPage[VulnerabilityResponse])
async def list_server_vulnerabilities(
    agent_id: str,
    cursor: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    severity: CVESeverity | None = Query(None),
    db: AsyncSession = Depends(get_db),
    cache: RedisCache = Depends(get_cache),
    _: dict = Depends(get_current_user),
) -> CursorPage[VulnerabilityResponse]:
    cache_key = f"vulnerability:{agent_id}:list:{severity}:{cursor}:{limit}"
    if hit := await cache.get_cached(cache_key):
        return CursorPage[VulnerabilityResponse].model_validate(hit)

    pk = parse_agent_pk(agent_id)
    agent = (await db.execute(
        select(Agent).where(Agent.id == pk)
    )).scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=404, detail="Server not found")

    q = (
        select(AgentVulnerability)
        .where(AgentVulnerability.agent_id == agent.id)
        .order_by(AgentVulnerability.discovered_at.desc(), AgentVulnerability.id.desc())
    )
    if severity:
        q = q.where(AgentVulnerability.severity == severity.value)
    if cursor:
        raw = decode_cursor(cursor)
        try:
            vuln_int = int(raw)
        except ValueError:
            raise HTTPException(status_code=400, detail="Malformed cursor")
        q = q.where(AgentVulnerability.id < vuln_int)

    q = q.limit(limit + 1)
    rows = (await db.execute(q)).scalars().all()

    has_more = len(rows) > limit
    items = rows[:limit]
    next_cursor = encode_cursor(str(items[-1].id)) if has_more and items else None

    page = CursorPage[VulnerabilityResponse](
        items=[VulnerabilityResponse.model_validate(v) for v in items],
        next_cursor=next_cursor,
    )
    await cache.set_cached(cache_key, json.loads(page.model_dump_json()), ttl=TTL_CVE_DATA)
    return page
