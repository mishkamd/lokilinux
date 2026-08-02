"""
LokiLinux — PolicyService: target resolution + policy-driven job creation.

The single place that turns a Policy's target_servers + actions[0] into a
real Job. Used by both the manual "Run now" endpoint and PolicySchedulerWorker
so the two paths can never drift apart.
"""

import logging
from datetime import datetime, timezone
from uuid import UUID

from croniter import croniter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.cache import RedisCache
from lokilinux.models.agent import Agent, AgentStatus
from lokilinux.models.job import Job
from lokilinux.models.policy import Policy, PolicyAudit
from lokilinux.services.job_service import JobService

logger = logging.getLogger(__name__)


def compute_next_run_at(cron_expr: str, base: datetime | None = None) -> datetime:
    """Next fire time strictly after `base` (default: now). Raises
    ValueError via croniter on a malformed expression — the router surfaces
    that as a 422 rather than silently accepting a policy that can never
    schedule."""
    return croniter(cron_expr, base or datetime.now(timezone.utc)).get_next(datetime)


async def resolve_targets(db: AsyncSession, target_servers: dict | None) -> list[UUID]:
    """Resolve a policy's target_servers into concrete agent PKs.

    Three shapes, the first two matching what PolicyWorker._resolve_scope
    already supports for the legacy /apply flow (kept identical so both
    paths agree on the same two forms):
      {"all": true}
      {"agent_ids": [...]}
      {"filters": {os_family?, os_distro?, category_id?, project_id?, status?}}
    The third is new — the only server-side targeting available before this
    (raw agent_ids only) couldn't express "every Rocky Linux box" or "every
    agent in this category" without the caller enumerating IDs by hand.
    """
    target_servers = target_servers or {}

    if target_servers.get("all"):
        rows = (await db.execute(select(Agent.id))).scalars().all()
        return list(rows)

    if agent_ids := target_servers.get("agent_ids"):
        return [UUID(a) if not isinstance(a, UUID) else a for a in agent_ids]

    filters = target_servers.get("filters")
    if filters:
        q = select(Agent.id)
        if v := filters.get("os_family"):
            q = q.where(Agent.os_family == v)
        if v := filters.get("os_distro"):
            q = q.where(Agent.os_distro == v)
        if v := filters.get("category_id"):
            q = q.where(Agent.category_id == UUID(v) if not isinstance(v, UUID) else v)
        if v := filters.get("project_id"):
            q = q.where(Agent.project_id == UUID(v) if not isinstance(v, UUID) else v)
        if v := filters.get("status"):
            q = q.where(Agent.status == AgentStatus(v))
        return list((await db.execute(q)).scalars().all())

    return []


async def run_policy(
    db: AsyncSession, policy: Policy, cache: RedisCache, *, triggered_by: str
) -> tuple[list[UUID], int]:
    """Resolve targets, create one Job from actions[0], write a PolicyAudit
    'TRIGGERED' row. Returns (job_ids, matched_agent_count) — job_ids is
    empty (not an error) when there are no actions, no matched agents, or an
    identical job is already active (JobService's own dedup) — a policy that
    fires often over a long-running job must skip quietly, not fail loudly.
    """
    agent_ids = await resolve_targets(db, policy.target_servers)

    job_ids: list[UUID] = []
    if agent_ids and policy.actions:
        action = policy.actions[0]
        job_svc = JobService(db, cache)
        try:
            job = await job_svc.create_job(
                name=f"{policy.name} ({triggered_by})",
                job_type=action["type"],
                target_servers={"agent_ids": [str(a) for a in agent_ids]},
                parameters=action.get("params") or {},
                policy_id=policy.id,
                requires_approval=bool((policy.execution or {}).get("requires_approval")),
            )
            job_ids = [job.id]
        except ValueError:
            logger.info("policy.run skipped — identical job already active", extra={"policy_id": str(policy.id)})

    db.add(PolicyAudit(
        policy_id=policy.id,
        change_type="TRIGGERED",
        new_value={"triggered_by": triggered_by, "matched_agents": len(agent_ids), "job_ids": [str(j) for j in job_ids]},
    ))
    await db.commit()

    return job_ids, len(agent_ids)


async def get_job_timeout_seconds(db: AsyncSession, job: Job) -> int | None:
    """A job's timeout comes from its originating policy's execution config
    — Job itself has no timeout column. Returns None (agent falls back to
    its own configured default) for manually-created jobs with no policy."""
    if not job.policy_id:
        return None
    policy = await db.get(Policy, job.policy_id)
    if not policy or not policy.execution:
        return None
    return policy.execution.get("timeout_seconds")
