"""
LokiLinux — Dashboard summary router.

Single aggregate endpoint backing the homepage: one round trip instead of
the frontend fanning out to every category's list endpoint just to read
counts.
"""

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.auth.dependencies import get_current_user
from lokilinux.dependencies import get_db
from lokilinux.models.agent import Agent, AgentStatus
from lokilinux.models.alert import Alert
from lokilinux.models.cve import AgentVulnerability
from lokilinux.models.job import Job, JobStatus
from lokilinux.models.plugin import Plugin
from lokilinux.models.policy import Policy

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

    vuln_by_severity = dict((
        await db.execute(
            select(AgentVulnerability.severity, func.count())
            .where(AgentVulnerability.is_remediated.is_(False))
            .group_by(AgentVulnerability.severity)
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
    }
