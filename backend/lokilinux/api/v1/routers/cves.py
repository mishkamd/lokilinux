"""
LokiLinux — CVE / Vulnerability router.

GET /vulnerabilities                        — global list, filter: severity, agent_id
GET /vulnerabilities/{cve_id}               — CVE detail
GET /servers/{agent_id}/vulnerabilities     — per-server CVEs
"""

import json
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.api.v1.routers._common import parse_agent_pk
from lokilinux.auth.dependencies import get_current_user
from lokilinux.cache import TTL_CVE_DATA, RedisCache
from lokilinux.dependencies import get_cache, get_db
from lokilinux.models.agent import Agent
from lokilinux.models.category import Category, Project
from lokilinux.models.cve import CVE, AgentVulnerability
from lokilinux.schemas.common import CursorPage, decode_cursor, encode_cursor
from lokilinux.schemas.cve import (
    CVEListResponse,
    CVEResponse,
    CVESeverity,
    CVESummary,
    PatchableVulnerability,
    TopVulnerableResource,
    VulnerabilityResourceDetail,
    VulnerabilityResponse,
    VulnerabilityStatus,
    VulnerabilitySummaryResponse,
    VulnerabilityTrendPoint,
)

router = APIRouter()

# statuses that count as "still exposed" for KPI/trend/top-N purposes —
# RESOLVED and ACCEPTED_RISK are deliberately excluded (docs/vulnerabilities
# V4): a resolved finding shouldn't inflate "how exposed is the fleet
# right now", and an accepted risk is a recorded decision, not an open gap.
_OPEN_STATUSES = ("OPEN", "PATCH_AVAILABLE", "IN_PROGRESS", "MITIGATED")

_TREND_RANGES = {"7d": (7, "1 day"), "30d": (30, "1 day"), "90d": (90, "1 day"), "1y": (365, "7 days")}


# ── Global CVE list ───────────────────────────────────────────────────────────

@router.get("", response_model=CVEListResponse)
async def list_vulnerabilities(
    cursor: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    severity: CVESeverity | None = Query(None),
    agent_id: str | None = Query(None),
    search: str | None = Query(None),
    exploited_only: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    cache: RedisCache = Depends(get_cache),
    _: dict = Depends(get_current_user),
) -> CVEListResponse:
    cache_key = f"cve:list:{severity}:{agent_id}:{search}:{exploited_only}:{cursor}:{limit}"
    if hit := await cache.get_cached(cache_key):
        return CVEListResponse.model_validate(hit)

    q = select(CVE).order_by(CVE.cvss_v3_score.desc().nullslast(), CVE.id.desc())
    count_q = select(func.count()).select_from(CVE)

    if severity:
        q = q.where(CVE.cvss_v3_severity == severity.value)
        count_q = count_q.where(CVE.cvss_v3_severity == severity.value)
    if agent_id:
        # subquery: CVEs affecting this agent
        sub = select(AgentVulnerability.cve_id).join(
            Agent, Agent.id == AgentVulnerability.agent_id
        ).where(Agent.agent_id == agent_id)
        q = q.where(CVE.cve_id.in_(sub))
        count_q = count_q.where(CVE.cve_id.in_(sub))
    if exploited_only:
        q = q.where(CVE.is_actively_exploited.is_(True))
        count_q = count_q.where(CVE.is_actively_exploited.is_(True))
    if search:
        fts = func.to_tsvector("english", func.coalesce(CVE.title, "") + " " + func.coalesce(CVE.description, ""))
        match = fts.op("@@")(func.plainto_tsquery("english", search))
        q = q.where(match)
        count_q = count_q.where(match)

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
    total = (await db.execute(count_q)).scalar_one()

    has_more = len(rows) > limit
    items = rows[:limit]
    next_cursor = encode_cursor(str(items[-1].id)) if has_more and items else None

    # affected_count per CVE in this page — a single GROUP BY, not N+1.
    # Distinct agent_id, not row count: the same CVE routinely hits more
    # than one package on the same host (confirmed live: CVE-2026-59858 via
    # both vim-minimal and vim-filesystem on one agent) — "servers affected"
    # means hosts, not (CVE, package) rows.
    cve_ids = [c.cve_id for c in items]
    affected_by_cve: dict[str, int] = {}
    if cve_ids:
        affected_rows = (await db.execute(
            select(AgentVulnerability.cve_id, func.count(func.distinct(AgentVulnerability.agent_id)))
            .where(AgentVulnerability.cve_id.in_(cve_ids), AgentVulnerability.is_remediated.is_(False))
            .group_by(AgentVulnerability.cve_id)
        )).all()
        affected_by_cve = dict(affected_rows)

    # Summary is the global severity distribution, independent of the current
    # filters — the frontend's stat cards double as "how much is out there",
    # not "how much matches my current search".
    summary_rows = (await db.execute(
        select(CVE.cvss_v3_severity, func.count()).group_by(CVE.cvss_v3_severity)
    )).all()
    summary = CVESummary(**{sev: count for sev, count in summary_rows if sev in CVESummary.model_fields})

    page = CVEListResponse(
        items=[
            CVEResponse.model_validate(c).model_copy(update={"affected_count": affected_by_cve.get(c.cve_id, 0)})
            for c in items
        ],
        next_cursor=next_cursor,
        total=total,
        summary=summary,
    )
    await cache.set_cached(cache_key, json.loads(page.model_dump_json()), ttl=TTL_CVE_DATA)
    return page


# ── Dashboard aggregates ───────────────────────────────────────────────────────
# Registered before /{cve_id} — FastAPI matches routes in declaration order,
# and a literal path here would otherwise be swallowed by that path param.


@router.get("/summary", response_model=VulnerabilitySummaryResponse)
async def vulnerability_summary(
    db: AsyncSession = Depends(get_db),
    cache: RedisCache = Depends(get_cache),
    _: dict = Depends(get_current_user),
) -> VulnerabilitySummaryResponse:
    cache_key = "cve:summary"
    if hit := await cache.get_cached(cache_key):
        return VulnerabilitySummaryResponse.model_validate(hit)

    resources_scanned = (
        await db.execute(select(func.count(func.distinct(AgentVulnerability.agent_id))))
    ).scalar_one()
    resources_total = (await db.execute(select(func.count()).select_from(Agent))).scalar_one()

    counts = dict(
        (await db.execute(
            select(AgentVulnerability.severity, func.count())
            .where(AgentVulnerability.status.in_(_OPEN_STATUSES))
            .group_by(AgentVulnerability.severity)
        )).all()
    )

    # Delta vs the prior 7-day window, by count of findings discovered in
    # each window and still open today — a real signal ("is this getting
    # worse"), not a fabricated placeholder.
    now = datetime.now(timezone.utc)
    week_ago, two_weeks_ago = now - timedelta(days=7), now - timedelta(days=14)
    prior_counts = dict(
        (await db.execute(
            select(AgentVulnerability.severity, func.count())
            .where(
                AgentVulnerability.status.in_(_OPEN_STATUSES),
                AgentVulnerability.discovered_at >= two_weeks_ago,
                AgentVulnerability.discovered_at < week_ago,
            )
            .group_by(AgentVulnerability.severity)
        )).all()
    )
    current_counts = dict(
        (await db.execute(
            select(AgentVulnerability.severity, func.count())
            .where(
                AgentVulnerability.status.in_(_OPEN_STATUSES),
                AgentVulnerability.discovered_at >= week_ago,
            )
            .group_by(AgentVulnerability.severity)
        )).all()
    )

    def _delta_pct(sev: str) -> float | None:
        prior, current = prior_counts.get(sev, 0), current_counts.get(sev, 0)
        if prior == 0:
            return None  # nothing to compare against — not "0%", genuinely unknown
        return round(100.0 * (current - prior) / prior, 1)

    resp = VulnerabilitySummaryResponse(
        resources_scanned=resources_scanned,
        resources_total=resources_total,
        critical=counts.get("CRITICAL", 0),
        high=counts.get("HIGH", 0),
        medium=counts.get("MEDIUM", 0),
        low=counts.get("LOW", 0),
        critical_delta_pct=_delta_pct("CRITICAL"),
        high_delta_pct=_delta_pct("HIGH"),
        medium_delta_pct=_delta_pct("MEDIUM"),
    )
    await cache.set_cached(cache_key, json.loads(resp.model_dump_json()), ttl=TTL_CVE_DATA)
    return resp


@router.get("/trend", response_model=list[VulnerabilityTrendPoint])
async def vulnerability_trend(
    range: str = Query("30d", pattern="^(7d|30d|90d|1y)$"),
    db: AsyncSession = Depends(get_db),
    cache: RedisCache = Depends(get_cache),
    _: dict = Depends(get_current_user),
) -> list[VulnerabilityTrendPoint]:
    """Derived retroactively from discovered_at/remediation_date — no
    snapshot table needed. For each day in the window, a finding counts as
    open if it was discovered on/before that day and either never resolved
    or resolved after that day. Verified live against the real DB before
    this was written (docs/vulnerabilities V4's design note)."""
    cache_key = f"cve:trend:{range}"
    if hit := await cache.get_cached(cache_key):
        return [VulnerabilityTrendPoint.model_validate(p) for p in hit]

    days, bucket = _TREND_RANGES[range]
    rows = (
        await db.execute(
            text(
                """
                SELECT d::date AS day,
                       count(*) FILTER (WHERE av.severity = 'CRITICAL') AS critical,
                       count(*) FILTER (WHERE av.severity = 'HIGH') AS high,
                       count(*) FILTER (WHERE av.severity = 'MEDIUM') AS medium,
                       count(*) FILTER (WHERE av.severity = 'LOW') AS low
                FROM generate_series(now() - (:days || ' days')::interval, now(), (:bucket)::interval) d
                LEFT JOIN agent_vulnerabilities av
                  ON av.discovered_at <= d
                 AND (av.remediation_date IS NULL OR av.remediation_date > d)
                GROUP BY d
                ORDER BY d
                """
            ),
            {"days": days, "bucket": bucket},
        )
    ).mappings().all()

    points = [VulnerabilityTrendPoint(**r) for r in rows]
    await cache.set_cached(cache_key, json.loads(json.dumps([p.model_dump(mode="json") for p in points])), ttl=TTL_CVE_DATA)
    return points


@router.get("/top-resources", response_model=list[TopVulnerableResource])
async def top_vulnerable_resources(
    limit: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    cache: RedisCache = Depends(get_cache),
    _: dict = Depends(get_current_user),
) -> list[TopVulnerableResource]:
    cache_key = f"cve:top-resources:{limit}"
    if hit := await cache.get_cached(cache_key):
        return [TopVulnerableResource.model_validate(r) for r in hit]

    rows = (
        await db.execute(
            text(
                """
                SELECT a.id AS agent_id, a.hostname, cat.name AS environment, proj.name AS project,
                       a.os_distro, a.os_version,
                       count(*) FILTER (WHERE av.severity = 'CRITICAL') AS critical,
                       count(*) FILTER (WHERE av.severity = 'HIGH') AS high,
                       count(*) FILTER (WHERE av.severity = 'MEDIUM') AS medium,
                       count(*) FILTER (WHERE av.severity = 'LOW') AS low,
                       count(*) AS total
                FROM agent_vulnerabilities av
                JOIN agents a ON a.id = av.agent_id
                LEFT JOIN categories cat ON cat.id = a.category_id
                LEFT JOIN projects proj ON proj.id = a.project_id
                WHERE av.status = ANY(:open_statuses)
                GROUP BY a.id, a.hostname, cat.name, proj.name, a.os_distro, a.os_version
                ORDER BY total DESC
                LIMIT :limit
                """
            ),
            {"open_statuses": list(_OPEN_STATUSES), "limit": limit},
        )
    ).mappings().all()

    resources = [TopVulnerableResource(**r) for r in rows]
    await cache.set_cached(cache_key, json.loads(json.dumps([r.model_dump(mode="json") for r in resources])), ttl=TTL_CVE_DATA)
    return resources


@router.get("/patchable", response_model=list[PatchableVulnerability])
async def top_patchable_vulnerabilities(
    limit: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    cache: RedisCache = Depends(get_cache),
    _: dict = Depends(get_current_user),
) -> list[PatchableVulnerability]:
    cache_key = f"cve:patchable:{limit}"
    if hit := await cache.get_cached(cache_key):
        return [PatchableVulnerability.model_validate(r) for r in hit]

    rows = (
        await db.execute(
            select(
                AgentVulnerability.cve_id,
                CVE.cvss_v3_score,
                CVE.cvss_v3_severity,
                AgentVulnerability.package_name,
                func.max(AgentVulnerability.fixed_version).label("fixed_version"),
                func.count(func.distinct(AgentVulnerability.agent_id)).label("affected_count"),
            )
            .join(CVE, CVE.cve_id == AgentVulnerability.cve_id)
            .where(
                AgentVulnerability.status.in_(_OPEN_STATUSES),
                AgentVulnerability.fix_available.is_(True),
            )
            .group_by(AgentVulnerability.cve_id, CVE.cvss_v3_score, CVE.cvss_v3_severity, AgentVulnerability.package_name)
            .order_by(func.count(func.distinct(AgentVulnerability.agent_id)).desc())
            .limit(limit)
        )
    ).all()

    items = [
        PatchableVulnerability(
            cve_id=r.cve_id, cvss_v3_score=r.cvss_v3_score, cvss_v3_severity=r.cvss_v3_severity,
            package_name=r.package_name, fixed_version=r.fixed_version, affected_count=r.affected_count,
        )
        for r in rows
    ]
    await cache.set_cached(cache_key, json.loads(json.dumps([i.model_dump(mode="json") for i in items])), ttl=TTL_CVE_DATA)
    return items


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
        items=[
            VulnerabilityResponse.model_validate(v).model_copy(update={"hostname": agent.hostname})
            for v in items
        ],
        next_cursor=next_cursor,
    )
    await cache.set_cached(cache_key, json.loads(page.model_dump_json()), ttl=TTL_CVE_DATA)
    return page


# ── Affected resources for a CVE ────────────────────────────────────────────────

@router.get("/{cve_id}/resources", response_model=list[VulnerabilityResourceDetail])
async def cve_affected_resources(
    cve_id: str,
    db: AsyncSession = Depends(get_db),
    cache: RedisCache = Depends(get_cache),
    _: dict = Depends(get_current_user),
) -> list[VulnerabilityResourceDetail]:
    cache_key = f"cve:{cve_id}:resources"
    if hit := await cache.get_cached(cache_key):
        return [VulnerabilityResourceDetail.model_validate(r) for r in hit]

    rows = (
        await db.execute(
            select(AgentVulnerability, Agent, Category.name, Project.name)
            .join(Agent, Agent.id == AgentVulnerability.agent_id)
            .outerjoin(Category, Category.id == Agent.category_id)
            .outerjoin(Project, Project.id == Agent.project_id)
            .where(AgentVulnerability.cve_id == cve_id)
            .order_by(AgentVulnerability.status, Agent.hostname)
        )
    ).all()

    resources = [
        VulnerabilityResourceDetail(
            agent_id=av.agent_id,
            hostname=agent.hostname,
            ip=agent.last_heartbeat_ip,
            os_distro=agent.os_distro,
            os_version=agent.os_version,
            package_name=av.package_name,
            package_version=av.package_version,
            fixed_version=av.fixed_version,
            environment=cat_name,
            project=proj_name,
            last_scan_at=av.last_scan_at,
            status=av.status,
        )
        for av, agent, cat_name, proj_name in rows
    ]
    await cache.set_cached(
        cache_key, json.loads(json.dumps([r.model_dump(mode="json") for r in resources])), ttl=TTL_CVE_DATA
    )
    return resources
