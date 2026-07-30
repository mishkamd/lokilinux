"""
LokiLinux — AgentService: heartbeat updates, pending-job dispatch, inactivity marking.
"""

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import and_, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.cache import RedisCache
from lokilinux.models.agent import Agent, AgentHealth as AgentHealthRow, AgentStatus
from lokilinux.models.cve import Package
from lokilinux.models.job import JobResult
from lokilinux.services.job_service import recompute_job_status

# health % thresholds above which the dashboard should flag the resource as critical
_DISK_FULL_THRESHOLD = 90.0
_MEMORY_CRITICAL_THRESHOLD = 90.0

# proto JobState enum values (agent/gen/lokilinux/lokilinux.pb.go) -> JobResult.status
_JOB_STATE_TO_STATUS = {
    0: "PENDING",
    1: "RUNNING",
    2: "COMPLETED",
    3: "FAILED",
    4: "TIMEOUT",
    5: "CANCELLED",
    6: "FAILED",  # rolled back — surfaced as failed, no dedicated status column value
}

# system_status keys (agent JSON) -> Agent column names
_SYSTEM_STATUS_FIELDS = (
    "hostname", "fqdn", "os_family", "os_distro", "os_version", "kernel_version", "arch",
)

# system_status keys carrying full-snapshot hardware lists (JSONB columns) —
# overwritten wholesale each heartbeat, unlike the scalar fields above.
_SYSTEM_HARDWARE_FIELDS = ("disks", "network_interfaces", "block_devices", "listening_ports")


class AgentService:
    def __init__(self, db: AsyncSession, cache: RedisCache) -> None:
        self.db = db
        self.cache = cache

    async def update_heartbeat(self, agent_id: str, data: dict) -> Agent:
        """Set last_heartbeat to now and status to ACTIVE; sync system info + packages; invalidate cache.

        Looked up by the agent's identity string (Agent.agent_id), not the DB PK —
        that's the id the agent reports in its heartbeat.
        """
        agent = (
            await self.db.execute(select(Agent).where(Agent.agent_id == str(agent_id)))
        ).scalar_one_or_none()
        if not agent:
            raise ValueError(f"Agent {agent_id} not found")
        agent.last_heartbeat = datetime.now(timezone.utc)
        agent.status = AgentStatus.ACTIVE
        if "ip_address" in data:
            agent.last_heartbeat_ip = data["ip_address"]

        system_status = data.get("system_status") or {}
        for field in _SYSTEM_HARDWARE_FIELDS:
            value = system_status.get(field)
            if value is not None:
                setattr(agent, field, value)
        for field in _SYSTEM_STATUS_FIELDS:
            value = system_status.get(field)
            if value:
                setattr(agent, field, value)
        system_users = system_status.get("system_users")
        if system_users is not None:
            agent.system_users = system_users

        if data.get("agent_version"):
            agent.agent_version = data["agent_version"]
        recent_logs = data.get("recent_logs")
        if recent_logs is not None:
            agent.recent_logs = {
                "lines": recent_logs,
                "connections": data.get("log_connections") or 0,
                "informative": data.get("log_informative") or 0,
                "critical": data.get("log_critical") or 0,
            }

        await self.db.commit()

        packages = data.get("packages")
        checksum = data.get("packages_checksum")
        if packages and checksum and checksum == agent.last_packages_checksum:
            pass  # unchanged since last heartbeat — skip the upsert entirely
        elif packages:
            await self._sync_packages(agent.id, packages)
            if checksum:
                agent.last_packages_checksum = checksum
                await self.db.commit()

        health = data.get("health")
        if health:
            await self._record_health(agent.id, health)

        job_results = data.get("job_results")
        if job_results:
            await self._apply_job_results(agent.id, job_results)

        # invalidate_agent must be keyed by PK — GET /servers/{pk} caches under
        # agent:{pk}:detail, but agent_id here is the agent's identity string
        # (what it reports in heartbeats), not the DB primary key.
        await self.cache.invalidate_agent(str(agent.id))
        return agent

    async def _sync_packages(self, agent_pk: UUID, packages: list[dict]) -> None:
        """Upsert the agent's reported package list.

        ponytail: only upserts what's reported — doesn't remove packages the
        agent no longer lists (would need a full-diff pass). Fine for v1;
        revisit if stale/uninstalled packages become a visible problem.
        """
        rows = [
            {
                "agent_id": agent_pk,
                "name": p["name"],
                "version": p["version"],
                "architecture": p.get("architecture") or None,
                "latest_version": p.get("latest_version") or None,
                "is_update_available": bool(p.get("update_available", False)),
                "is_security_update_available": bool(p.get("is_security_update", False)),
            }
            for p in packages
            if p.get("name") and p.get("version")
        ]
        if not rows:
            return

        stmt = pg_insert(Package).values(rows)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_packages_agent_name_version",
            set_={
                "architecture": stmt.excluded.architecture,
                "latest_version": stmt.excluded.latest_version,
                "is_update_available": stmt.excluded.is_update_available,
                "is_security_update_available": stmt.excluded.is_security_update_available,
                "last_update_check": datetime.now(timezone.utc),
            },
        )
        await self.db.execute(stmt)
        await self.db.commit()

    async def _record_health(self, agent_pk: UUID, health: dict) -> None:
        """Insert one AgentHealth snapshot per heartbeat (cpu/mem/disk %)."""
        memory_usage = health.get("memory_usage") or 0.0
        disk_usage = health.get("disk_usage") or 0.0
        self.db.add(AgentHealthRow(
            agent_id=agent_pk,
            cpu_usage=health.get("cpu_usage") or 0.0,
            cpu_count=health.get("cpu_count"),
            memory_usage=memory_usage,
            memory_total_bytes=health.get("memory_total_bytes"),
            memory_used_bytes=health.get("memory_used_bytes"),
            disk_usage=disk_usage,
            disk_total_bytes=health.get("disk_total_bytes"),
            disk_used_bytes=health.get("disk_used_bytes"),
            swap_usage=health.get("swap_usage"),
            swap_total_bytes=health.get("swap_total_bytes"),
            swap_used_bytes=health.get("swap_used_bytes"),
            is_disk_full=disk_usage >= _DISK_FULL_THRESHOLD,
            is_memory_critical=memory_usage >= _MEMORY_CRITICAL_THRESHOLD,
            connection_failures=health.get("connection_failures") or 0,
        ))
        await self.db.commit()

    async def _apply_job_results(self, agent_pk: UUID, job_results: list[dict]) -> None:
        """Update JobResult rows with outcomes the agent reports on its next
        heartbeat after executing a job (agent has no other channel back)."""
        touched_job_ids: set[UUID] = set()
        for r in job_results:
            job_id = r.get("job_id")
            if not job_id:
                continue
            row = (
                await self.db.execute(
                    select(JobResult).where(
                        and_(JobResult.job_id == UUID(job_id), JobResult.agent_id == agent_pk)
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                continue

            row.status = _JOB_STATE_TO_STATUS.get(r.get("state"), "COMPLETED")
            row.exit_code = r.get("exit_code")
            row.error_message = r.get("error_message") or None
            row.stdout = r.get("output") or None
            row.completed_at = datetime.now(timezone.utc)
            touched_job_ids.add(UUID(job_id))

        for jid in touched_job_ids:
            await recompute_job_status(self.db, jid)

        await self.db.commit()

        for jid in touched_job_ids:
            await self.cache.invalidate(f"job:{jid}:status")

    async def get_pending_jobs(self, agent_id: UUID) -> list:
        """Return Jobs assigned to this agent whose JobResult status is PENDING.

        Jobs with requires_approval=True are withheld until Job.approved_at
        is set (see JobService.approve_job) — otherwise an approval-gated
        job would still reach the agent on the very next heartbeat.

        Gates on approved_at, not approved_by: safe_user_uuid() frequently
        returns None even for a legitimate approver (Better Auth's nanoid
        user id often doesn't parse as UUID — see auth/dependencies.py), so
        approved_by can be NULL on a genuinely-approved job. approved_at is
        always set by JobService.approve_job regardless of that.
        """
        from lokilinux.models.job import Job, JobResult, JobStatus

        result = await self.db.execute(
            select(Job)
            .join(JobResult, JobResult.job_id == Job.id)
            .where(
                and_(
                    JobResult.agent_id == agent_id,
                    JobResult.status == "PENDING",
                    or_(
                        Job.requires_approval.is_(False),
                        Job.approved_at.isnot(None),
                    ),
                )
            )
            .limit(10)
        )
        jobs = result.scalars().all()

        # Mark as dispatched so the same job isn't re-selected (and re-sent
        # to the agent) on every subsequent heartbeat until a result comes
        # back — this SELECT used to be side-effect free, which meant a job
        # stayed QUEUED/PENDING for its entire run and got re-executed each
        # heartbeat. A job left RUNNING because the agent died is swept to
        # TIMEOUT by JobTimeoutWorker.
        if jobs:
            job_ids = [j.id for j in jobs]
            now = datetime.now(timezone.utc)
            await self.db.execute(
                update(JobResult)
                .where(
                    JobResult.job_id.in_(job_ids),
                    JobResult.agent_id == agent_id,
                    JobResult.status == "PENDING",
                )
                .values(status="RUNNING", started_at=now)
            )
            await self.db.execute(
                update(Job)
                .where(Job.id.in_(job_ids), Job.status.in_((JobStatus.QUEUED, JobStatus.SCHEDULED)))
                .values(status=JobStatus.RUNNING, started_at=now)
            )
            await self.db.commit()

        return jobs

    async def mark_inactive(self, agent_id: UUID) -> None:
        """Mark agent INACTIVE (called by a background stale-check task)."""
        await self.db.execute(
            update(Agent)
            .where(Agent.id == agent_id)
            .values(status=AgentStatus.INACTIVE)
        )
        await self.db.commit()
