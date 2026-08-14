"""
LokiLinux — Dashboard summary router.

GET /summary — single aggregate endpoint backing the homepage: one round
               trip instead of the frontend fanning out to every category's
               list endpoint just to read counts.
GET /trends  — per-day series (servers/vulnerabilities/jobs/alerts) for the
               dashboard's period-filtered charts.
"""

from datetime import date

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.auth.dependencies import get_current_user
from lokilinux.cache import TTL_DASHBOARD, RedisCache
from lokilinux.dependencies import get_cache, get_db
from lokilinux.models.agent import Agent, AgentStatus
from lokilinux.models.alert import Alert
from lokilinux.models.cve import CVE, AgentVulnerability
from lokilinux.models.job import Job, JobStatus
from lokilinux.models.plugin import Plugin
from lokilinux.models.policy import Policy
from lokilinux.services.trends import OPEN_VULN_STATUSES, TREND_RANGES, vulnerability_counts_by_day

router = APIRouter()


async def _counts_by(db: AsyncSession, column) -> dict[str, int]:
    rows = (await db.execute(select(column, func.count()).group_by(column))).all()
    return {(key.value if hasattr(key, "value") else key): count for key, count in rows}


@router.get("/summary")
async def get_dashboard_summary(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
) -> dict:
    agents_by_status = await _counts_by(db, Agent.status)
    agents_total = sum(agents_by_status.values())
    updates_available = (await db.execute(select(func.coalesce(func.sum(Agent.updates_available), 0)))).scalar_one()

    # coalesce NULL os_distro to a string — ORJSONResponse (main.py) rejects
    # non-str dict keys, and agents without a heartbeat yet have no os_distro.
    os_distro_col = func.coalesce(Agent.os_distro, "Unknown")
    os_distribution = dict((
        await db.execute(select(os_distro_col, func.count()).group_by(os_distro_col))
    ).all())

    # Severity from cves.cvss_v3_severity, not the denormalized
    # agent_vulnerabilities.severity snapshot — see services/trends.py.
    # Status-based "still open" filter (OPEN_VULN_STATUSES), matching
    # /vulnerabilities/summary and /cves/top-resources exactly — this used
    # to filter on is_remediated instead, a second definition that could
    # (and did) disagree with the rest of the app.
    vuln_by_severity = dict((
        await db.execute(
            select(CVE.cvss_v3_severity, func.count())
            .select_from(AgentVulnerability)
            .join(CVE, AgentVulnerability.cve_id == CVE.cve_id)
            .where(AgentVulnerability.status.in_(OPEN_VULN_STATUSES))
            .group_by(CVE.cvss_v3_severity)
        )
    ).all())
    vuln_unresolved_total = sum(vuln_by_severity.values())

    jobs_by_status = await _counts_by(db, Job.status)
    jobs_total = sum(jobs_by_status.values())
    jobs_running = jobs_by_status.get(JobStatus.RUNNING.value, 0)

    alerts_by_severity = dict((
        await db.execute(
            select(Alert.severity, func.count())
            .where(Alert.status == "ACTIVE")
            .group_by(Alert.severity)
        )
    ).all())
    alerts_active_total = sum(alerts_by_severity.values())

    policies_total = (await db.execute(select(func.count()).select_from(Policy))).scalar_one()
    policies_enabled = (
        await db.execute(select(func.count()).select_from(Policy).where(Policy.is_enabled.is_(True)))
    ).scalar_one()

    plugins_by_status = await _counts_by(db, Plugin.installation_status)
    plugins_total = sum(plugins_by_status.values())
    plugins_enabled = (
        await db.execute(select(func.count()).select_from(Plugin).where(Plugin.is_enabled.is_(True)))
    ).scalar_one()

    # Fleet-wide health — average of each agent's *latest* snapshot, not a
    # raw average over agent_health rows (that would over-weight agents that
    # report more often). DISTINCT ON is the standard Postgres "latest row
    # per group" idiom, same as compliance/dashboard.py's `latest` CTE.
    health_row = (
        await db.execute(
            text(
                """
                SELECT avg(cpu_usage) AS cpu_usage,
                       avg(memory_usage) AS memory_usage,
                       avg(disk_usage) AS disk_usage,
                       avg(network_latency_ms) AS network_latency_ms
                FROM (
                    SELECT DISTINCT ON (agent_id)
                        agent_id, cpu_usage, memory_usage, disk_usage, network_latency_ms
                    FROM agent_health
                    ORDER BY agent_id, recorded_at DESC
                ) latest
                """
            )
        )
    ).mappings().one()

    return {
        "agents": {
            "total": agents_total,
            "by_status": agents_by_status,
            "active": agents_by_status.get(AgentStatus.ACTIVE.value, 0),
            "updates_available": updates_available,
            "os_distribution": os_distribution,
        },
        "vulnerabilities": {
            "unresolved_total": vuln_unresolved_total,
            "by_severity": vuln_by_severity,
        },
        "jobs": {
            "total": jobs_total,
            "by_status": jobs_by_status,
            "running": jobs_running,
        },
        "alerts": {
            "active_total": alerts_active_total,
            "by_severity": alerts_by_severity,
        },
        "policies": {
            "total": policies_total,
            "enabled": policies_enabled,
        },
        "plugins": {
            "total": plugins_total,
            "enabled": plugins_enabled,
        },
        "health": {k: (round(v, 1) if v is not None else None) for k, v in health_row.items()},
    }


# ── Trend series ──────────────────────────────────────────────────────────────

class ServerTrendPoint(BaseModel):
    day: date
    total: int


class JobTrendPoint(BaseModel):
    day: date
    successful: int
    failed: int
    running: int


class AlertTrendPoint(BaseModel):
    day: date
    created: int
    resolved: int


class VulnerabilityTrendPoint(BaseModel):
    day: date
    critical: int
    high: int
    medium: int
    low: int


class DashboardTrends(BaseModel):
    servers: list[ServerTrendPoint]
    vulnerabilities: list[VulnerabilityTrendPoint]
    jobs: list[JobTrendPoint]
    alerts: list[AlertTrendPoint]


@router.get("/trends", response_model=DashboardTrends)
async def get_dashboard_trends(
    range: str = Query("30d", pattern="^(7d|30d|90d|1y)$"),
    db: AsyncSession = Depends(get_db),
    cache: RedisCache = Depends(get_cache),
    _: dict = Depends(get_current_user),
) -> DashboardTrends:
    cache_key = f"dashboard:trends:{range}"
    if hit := await cache.get_cached(cache_key):
        return DashboardTrends.model_validate(hit)

    days, bucket = TREND_RANGES[range]
    params = {"days": days, "bucket": bucket}

    vuln_rows = await vulnerability_counts_by_day(db, range)

    # Shared day-bucket series — every trend query below joins against it.
    series = """
        generate_series(now() - (:days || ' days')::interval, now(), (:bucket)::interval) d
    """

    server_rows = (
        await db.execute(
            text(
                f"""
                SELECT d::date AS day,
                       (SELECT count(*) FROM agents a WHERE a.registered_at <= d) AS total
                FROM {series}
                ORDER BY d
                """
            ),
            params,
        )
    ).mappings().all()

    job_rows = (
        await db.execute(
            text(
                f"""
                SELECT d::date AS day,
                       (SELECT count(*) FROM jobs j WHERE j.status = 'COMPLETED'
                          AND date_trunc('day', j.created_at) = date_trunc('day', d)) AS successful,
                       (SELECT count(*) FROM jobs j WHERE j.status IN ('FAILED', 'TIMEOUT')
                          AND date_trunc('day', j.created_at) = date_trunc('day', d)) AS failed,
                       (SELECT count(*) FROM jobs j WHERE j.status = 'RUNNING'
                          AND date_trunc('day', j.created_at) = date_trunc('day', d)) AS running
                FROM {series}
                ORDER BY d
                """
            ),
            params,
        )
    ).mappings().all()

    alert_rows = (
        await db.execute(
            text(
                f"""
                SELECT d::date AS day,
                       (SELECT count(*) FROM alerts al WHERE
                          date_trunc('day', al.triggered_at) = date_trunc('day', d)) AS created,
                       (SELECT count(*) FROM alerts al WHERE
                          date_trunc('day', al.resolved_at) = date_trunc('day', d)) AS resolved
                FROM {series}
                ORDER BY d
                """
            ),
            params,
        )
    ).mappings().all()

    trends = DashboardTrends(
        servers=[ServerTrendPoint(**r) for r in server_rows],
        vulnerabilities=[VulnerabilityTrendPoint(**r) for r in vuln_rows],
        jobs=[JobTrendPoint(**r) for r in job_rows],
        alerts=[AlertTrendPoint(**r) for r in alert_rows],
    )
    await cache.set_cached(cache_key, trends.model_dump(mode="json"), ttl=TTL_DASHBOARD)
    return trends
