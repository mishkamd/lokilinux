"""
LokiLinux — CVE / Vulnerability router.

GET /vulnerabilities                        — global list, filter: severity, agent_id
GET /vulnerabilities/{cve_id}               — CVE detail
GET /servers/{agent_id}/vulnerabilities     — per-server CVEs
"""

import csv
import io
import json
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.api.v1.routers._common import parse_agent_pk
from lokilinux.auth.dependencies import get_current_user, require_role, safe_user_uuid
from lokilinux.cache import TTL_CVE_DATA, RedisCache
from lokilinux.dependencies import get_cache, get_db, get_nats
from lokilinux.models.agent import Agent
from lokilinux.models.category import Category, Project
from lokilinux.models.cve import CVE, AgentVulnerability
from lokilinux.schemas.common import CursorPage, decode_cursor, encode_cursor
from lokilinux.schemas.cve import (
    AcceptRiskRequest,
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
from lokilinux.schemas.remediation import RemediationActionCreate, RemediationPlanResponse
from lokilinux.services.audit_service import AuditService
from lokilinux.services.job_service import JobService
from lokilinux.services.remediation_service import RemediationService

router = APIRouter()

# statuses that count as "still exposed" for KPI/trend/top-N purposes —
# RESOLVED and ACCEPTED_RISK are deliberately excluded (docs/vulnerabilities
# V4): a resolved finding shouldn't inflate "how exposed is the fleet
# right now", and an accepted risk is a recorded decision, not an open gap.
_OPEN_STATUSES = ("OPEN", "PATCH_AVAILABLE", "IN_PROGRESS", "MITIGATED")

_TREND_RANGES = {"7d": (7, "1 day"), "30d": (30, "1 day"), "90d": (90, "1 day"), "1y": (365, "7 days")}

# os_distro -> upgrade-to-latest command. The Go agent picks its package
# manager by checking which binary actually exists on disk (package_manager.
# go detectPackageManager) — the backend only knows os_distro/os_family, so
# this is a heuristic on distro family, not binary detection. Every agent in
# this fleet today is rocky (dnf); ponytail: extend the map when a real
# apt/zypper host shows up and this guess turns out wrong for it.
_UPGRADE_CMD = {
    "debian": 'apt-get update && apt-get install --only-upgrade -y "{pkg}"',
    "ubuntu": 'apt-get update && apt-get install --only-upgrade -y "{pkg}"',
    "rhel": 'dnf upgrade -y "{pkg}"',
    "rocky": 'dnf upgrade -y "{pkg}"',
    "centos": 'dnf upgrade -y "{pkg}"',
    "almalinux": 'dnf upgrade -y "{pkg}"',
    "fedora": 'dnf upgrade -y "{pkg}"',
    "opensuse": 'zypper update -y "{pkg}"',
    "sles": 'zypper update -y "{pkg}"',
}


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


@router.get("/export")
async def export_vulnerabilities(
    format: str = Query("csv", pattern="^(csv|json)$"),
    severity: CVESeverity | None = Query(None),
    exploited_only: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
) -> Response:
    """Exports the CVE catalog (one row per CVE, matching the catalog
    list's grain — not per-finding). Capped at 10,000 rows: a fleet-scale
    export belongs on the existing Compliance report generator's async
    job pattern (services/report_service.py), not a synchronous request —
    this is the honest ceiling for "download the current filtered view,"
    not a promise to export the whole catalog at 100K-server scale."""
    q = select(CVE).order_by(CVE.cvss_v3_score.desc().nullslast(), CVE.id.desc()).limit(10_000)
    if severity:
        q = q.where(CVE.cvss_v3_severity == severity.value)
    if exploited_only:
        q = q.where(CVE.is_actively_exploited.is_(True))
    rows = (await db.execute(q)).scalars().all()

    fields = [
        "cve_id", "cvss_v3_severity", "cvss_v3_score", "title", "is_actively_exploited",
        "is_zero_day", "published_date", "enrichment_status",
    ]

    if format == "json":
        payload = [
            {f: (getattr(r, f).isoformat() if hasattr(getattr(r, f), "isoformat") else getattr(r, f)) for f in fields}
            for r in rows
        ]
        return Response(
            content=json.dumps(payload, indent=2),
            media_type="application/json",
            headers={"Content-Disposition": "attachment; filename=vulnerabilities.json"},
        )

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fields)
    writer.writeheader()
    for r in rows:
        writer.writerow({f: getattr(r, f) for f in fields})
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=vulnerabilities.csv"},
    )


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


# ── Remediation ───────────────────────────────────────────────────────────────

@router.post("/{cve_id}/remediate", response_model=RemediationPlanResponse, status_code=201)
async def remediate_cve(
    cve_id: str,
    agent_ids: list[UUID] | None = None,
    maintenance_window_id: UUID | None = None,
    is_emergency: bool = False,
    db: AsyncSession = Depends(get_db),
    cache: RedisCache = Depends(get_cache),
    nats=Depends(get_nats),
    current_user: dict = Depends(require_role("ADMIN", "OPERATOR")),
) -> RemediationPlanResponse:
    """Builds one shell-provider RemediationAction per affected (agent,
    package) pair — reuses the existing RemediationPlan engine wholesale
    (approval, maintenance window, dry-run, rollback all come free) rather
    than a parallel dispatch path. No agent-side change: this is "upgrade
    to whatever's latest", the same ceiling PACKAGE_UPDATE already has —
    not a pinned-version install (package_updater.go's argv only takes
    package names)."""
    findings_q = (
        select(AgentVulnerability, Agent)
        .join(Agent, Agent.id == AgentVulnerability.agent_id)
        .where(
            AgentVulnerability.cve_id == cve_id,
            AgentVulnerability.status.in_(_OPEN_STATUSES),
            AgentVulnerability.fix_available.is_(True),
        )
    )
    if agent_ids:
        findings_q = findings_q.where(AgentVulnerability.agent_id.in_(agent_ids))
    findings = (await db.execute(findings_q)).all()
    if not findings:
        raise HTTPException(status_code=404, detail="No open, patchable findings for this CVE (for the given agents)")

    actions: list[RemediationActionCreate] = []
    for av, agent in findings:
        cmd_template = _UPGRADE_CMD.get((agent.os_distro or "").lower(), _UPGRADE_CMD["rocky"])
        actions.append(RemediationActionCreate(
            agent_id=av.agent_id,
            provider="shell",
            rendered_body=cmd_template.format(pkg=av.package_name),
        ))

    remediation_svc = RemediationService(db, JobService(db, cache, nats))
    plan = await remediation_svc.create_plan(
        name=f"Patch {cve_id} ({len(actions)} action{'s' if len(actions) != 1 else ''})",
        trigger_type="MANUAL",
        actions=actions,
        is_emergency=is_emergency,
        maintenance_window_id=maintenance_window_id,
        created_by=safe_user_uuid(current_user),
    )

    # Reflect "someone is actively working this" immediately — the plan
    # engine's own verification (via the reconciliation fix: a genuine next
    # scan that no longer reports the finding) is what actually resolves it,
    # not this status write. _plan_has_verifiable_actions requires rule_id,
    # which these shell actions never carry, so the plan itself completes on
    # exit code alone — real confirmation is the next heartbeat, matching
    # this module's "never trust exit 0 = fixed" rule elsewhere.
    finding_ids = [av.id for av, _agent in findings]
    await db.execute(
        AgentVulnerability.__table__.update()
        .where(AgentVulnerability.id.in_(finding_ids))
        .values(status="IN_PROGRESS", remediation_plan_id=plan.id)
    )
    await db.commit()

    await AuditService(db).log(
        action="vulnerability.remediation_requested",
        user_id=current_user.get("id"),
        actor_name=current_user.get("username") or current_user.get("email"),
        resource_type="cve",
        resource_id=cve_id,
        changes={"remediation_plan_id": str(plan.id), "agent_count": len(findings)},
    )
    return RemediationPlanResponse.model_validate(plan)


@router.post("/{cve_id}/accept-risk", response_model=list[VulnerabilityResourceDetail])
async def accept_risk(
    cve_id: str,
    body: AcceptRiskRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("ADMIN")),
) -> list[VulnerabilityResourceDetail]:
    q = select(AgentVulnerability).where(
        AgentVulnerability.cve_id == cve_id,
        AgentVulnerability.status.in_(_OPEN_STATUSES),
    )
    if body.agent_ids:
        q = q.where(AgentVulnerability.agent_id.in_(body.agent_ids))
    rows = (await db.execute(q)).scalars().all()
    if not rows:
        raise HTTPException(status_code=404, detail="No open findings for this CVE (for the given agents)")

    actor_id = safe_user_uuid(current_user)
    for row in rows:
        row.status = "ACCEPTED_RISK"
        row.accepted_risk_by = actor_id
        row.accepted_risk_reason = body.reason
        row.accepted_risk_until = body.until
    await db.commit()

    await AuditService(db).log(
        action="vulnerability.risk_accepted",
        user_id=current_user.get("id"),
        actor_name=current_user.get("username") or current_user.get("email"),
        resource_type="cve",
        resource_id=cve_id,
        changes={"reason": body.reason, "agent_count": len(rows), "until": body.until.isoformat() if body.until else None},
    )

    detail_rows = (
        await db.execute(
            select(AgentVulnerability, Agent, Category.name, Project.name)
            .join(Agent, Agent.id == AgentVulnerability.agent_id)
            .outerjoin(Category, Category.id == Agent.category_id)
            .outerjoin(Project, Project.id == Agent.project_id)
            .where(AgentVulnerability.id.in_([r.id for r in rows]))
        )
    ).all()
    return [
        VulnerabilityResourceDetail(
            agent_id=av.agent_id, hostname=agent.hostname, ip=agent.last_heartbeat_ip,
            os_distro=agent.os_distro, os_version=agent.os_version,
            package_name=av.package_name, package_version=av.package_version, fixed_version=av.fixed_version,
            environment=cat_name, project=proj_name, last_scan_at=av.last_scan_at, status=av.status,
        )
        for av, agent, cat_name, proj_name in detail_rows
    ]


@router.post("/{cve_id}/rescan", status_code=202)
async def rescan_cve(
    cve_id: str,
    agent_ids: list[UUID] | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("ADMIN", "OPERATOR")),
) -> dict:
    """There is no CVE_SCAN agent handler (agent/internal/agent/manager.go
    only implements PLUGIN_INSTALL/PACKAGE_UPDATE/ANSIBLE_PLAYBOOK/
    COMPLIANCE_REMEDIATE) — building one is out of this phase's scope.
    Clearing last_packages_checksum forces the real path instead: the
    agent's next heartbeat always computes vulnerabilities fresh regardless
    of the checksum (agent_service.py's reconciliation-fix comment), so
    this just guarantees _sync_packages also runs instead of being skipped
    as unchanged, giving the freshest possible package/vuln state."""
    q = select(Agent.id).join(AgentVulnerability, AgentVulnerability.agent_id == Agent.id).where(
        AgentVulnerability.cve_id == cve_id,
        AgentVulnerability.status.in_(_OPEN_STATUSES),
    ).distinct()
    if agent_ids:
        q = q.where(Agent.id.in_(agent_ids))
    targets = (await db.execute(q)).scalars().all()
    if not targets:
        raise HTTPException(status_code=404, detail="No affected agents to rescan for this CVE")

    await db.execute(
        Agent.__table__.update().where(Agent.id.in_(targets)).values(last_packages_checksum=None)
    )
    await db.commit()

    await AuditService(db).log(
        action="vulnerability.rescan_requested",
        user_id=current_user.get("id"),
        actor_name=current_user.get("username") or current_user.get("email"),
        resource_type="cve",
        resource_id=cve_id,
        changes={"agent_count": len(targets)},
    )
    return {"agents_queued": len(targets)}
