"""
LokiLinux — JobService: job creation with dedup, result persistence.

Job targets agents via target_servers JSONB — there is no single agent_id FK on Job.
Per-agent execution state lives in JobResult (agent_id FK required).
"""

import hashlib
import json
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.cache import RedisCache, TTL_JOB_STATUS
from lokilinux.models.job import Job, JobResult, JobStatus
from lokilinux.models.plugin import Plugin, PluginInstallation, PluginStatus
from lokilinux.nats_topics import JOB_CREATED

_TERMINAL_RESULT_STATUSES = {"COMPLETED", "FAILED", "TIMEOUT", "CANCELLED", "SKIPPED"}
_FAILURE_PRIORITY = ("FAILED", "TIMEOUT", "CANCELLED")  # first match wins; else COMPLETED


async def recompute_job_status(db: AsyncSession, job_id: UUID) -> None:
    """Recompute Job.status from its JobResult rows. Call after any
    JobResult.status mutation, before the caller's commit.

    ponytail: re-reads all JobResult rows per call instead of incremental/
    locked state — fan-out is per-agent (small N), and two agents finishing
    concurrently each recompute from the same terminal set, so last-write-wins
    still converges correctly. Add SELECT FOR UPDATE only if concurrent writes
    are observed to actually diverge.
    """
    await db.flush()  # session has autoflush=False — make pending JobResult writes visible
    rows = (
        await db.execute(select(JobResult).where(JobResult.job_id == job_id))
    ).scalars().all()
    if not rows:
        return

    job = await db.get(Job, job_id)
    if job is None or job.status == JobStatus.CANCELLED:
        return  # manual cancel is final — a late agent report can't reopen it

    statuses = [r.status for r in rows]
    all_terminal = all(s in _TERMINAL_RESULT_STATUSES for s in statuses)
    now = datetime.now(timezone.utc)

    if not all_terminal:
        if any(s in _TERMINAL_RESULT_STATUSES for s in statuses):
            job.status = JobStatus.RUNNING
            if job.started_at is None:
                job.started_at = now
    else:
        job.status = next(
            (JobStatus[s] for s in _FAILURE_PRIORITY if s in statuses),
            JobStatus.COMPLETED,
        )
        if job.completed_at is None:
            job.completed_at = now

    if job.job_type == "PLUGIN_INSTALL":
        await _sync_plugin_installations(db, job, rows)


async def _sync_plugin_installations(db: AsyncSession, job: Job, results) -> None:
    """Propagate PLUGIN_INSTALL job results into PluginInstallation rows and
    aggregate Plugin.installation_status. Runs on every recompute so per-agent
    progress is visible before the whole fan-out finishes; idempotent."""
    raw_plugin_id = (job.parameters or {}).get("plugin_id")
    if not raw_plugin_id:
        return
    plugin = await db.get(Plugin, UUID(raw_plugin_id))
    # Only sync while an install is in flight — a late duplicate result must
    # not clobber a plugin the user has since enabled/disabled.
    if plugin is None or plugin.installation_status not in (
        PluginStatus.INSTALLING,
        PluginStatus.INSTALLING_FAILED,
    ):
        return

    installations = (
        await db.execute(
            select(PluginInstallation).where(PluginInstallation.plugin_id == plugin.id)
        )
    ).scalars().all()
    by_agent = {i.agent_id: i for i in installations}
    now = datetime.now(timezone.utc)

    for r in results:
        inst = by_agent.get(r.agent_id)
        if inst is None or r.status not in _TERMINAL_RESULT_STATUSES:
            continue
        if r.status == "COMPLETED":
            inst.status = "INSTALLED"
            inst.error_message = None
            inst.installed_at = inst.installed_at or now
        else:
            inst.status = "ERROR"
            inst.error_message = r.error_message or r.stderr or f"install {r.status.lower()}"

    statuses = {i.status for i in installations}
    if statuses and statuses <= {"INSTALLED"}:
        plugin.installation_status = PluginStatus.INSTALLED
        plugin.is_installed = True
        plugin.installed_at = plugin.installed_at or now
    elif "ERROR" in statuses:
        plugin.installation_status = PluginStatus.INSTALLING_FAILED


class JobService:
    def __init__(self, db: AsyncSession, cache: RedisCache, nats=None) -> None:
        self.db = db
        self.cache = cache
        self.nats = nats

    @staticmethod
    def compute_dedup_key(job_type: str, target_servers: dict, parameters: dict) -> str:
        raw = f"{job_type}:{json.dumps(target_servers, sort_keys=True)}:{json.dumps(parameters, sort_keys=True)}"
        return hashlib.sha256(raw.encode()).hexdigest()

    async def create_job(
        self,
        name: str,
        job_type: str,
        target_servers: dict,
        parameters: dict | None = None,
        description: str | None = None,
        scheduled_time: datetime | None = None,
        policy_id: UUID | None = None,
        created_by: UUID | None = None,
        requires_approval: bool = False,
    ) -> Job:
        """Create a job; raise ValueError on active duplicate.

        Fans out a JobResult(status=PENDING) row per target agent — this is
        what makes the job visible to AgentService.get_pending_jobs().
        """
        params = parameters or {}
        dedup_key = self.compute_dedup_key(job_type, target_servers, params)

        existing = await self.db.execute(
            select(Job).where(
                Job.dedup_key == dedup_key,
                Job.status.in_([
                    JobStatus.QUEUED, JobStatus.SCHEDULED,
                    JobStatus.PENDING, JobStatus.RUNNING,
                ]),
            )
        )
        if existing.scalar_one_or_none():
            raise ValueError("Duplicate job already active")

        agent_ids: list[str] = target_servers.get("agent_ids", [])
        agent_uuids = [UUID(aid) for aid in agent_ids]

        job = Job(
            name=name,
            job_type=job_type,
            description=description,
            target_servers=target_servers,
            parameters=params,
            scheduled_time=scheduled_time,
            policy_id=policy_id,
            created_by=created_by,
            dedup_key=dedup_key,
            total_servers=len(agent_uuids) or None,
            requires_approval=requires_approval,
        )
        self.db.add(job)
        await self.db.flush()  # populate job.id before building JobResult rows

        if agent_uuids:
            self.db.add_all([
                JobResult(job_id=job.id, agent_id=aid, status="PENDING")
                for aid in agent_uuids
            ])

        try:
            await self.db.commit()
        except IntegrityError as exc:
            # uq_jobs_dedup_key (migration 020) covers the same active statuses
            # the check above does, so reaching here means another request won
            # the race between our SELECT and this commit. Same outcome for the
            # caller as the check catching it — a 409, not a 500.
            await self.db.rollback()
            raise ValueError("Duplicate job already active") from exc

        # A job requiring approval must not reach agents until approved —
        # get_pending_jobs() filters these out until approved_by is set.
        # Publishing "created" is still useful for dashboard visibility.
        if self.nats:
            await self.nats.publish(
                JOB_CREATED,
                json.dumps({"job_id": str(job.id)}).encode(),
            )
        return job

    async def approve_job(self, job_id: UUID, approved_by: UUID | None) -> Job:
        """Approve a job that requires_approval — makes it eligible for
        agent pickup on the next heartbeat (see AgentService.get_pending_jobs)."""
        job = await self.db.get(Job, job_id)
        if job is None:
            raise ValueError(f"Job {job_id} not found")
        if not job.requires_approval:
            raise ValueError("Job does not require approval")
        if job.approved_at is not None:
            # approved_by can be NULL even for a real approver — Better
            # Auth's nanoid user id often fails to parse as UUID (see
            # safe_user_uuid) — so approved_at is the reliable "done" flag.
            raise ValueError("Job already approved")

        job.approved_by = approved_by
        job.approved_at = datetime.now(timezone.utc)
        await self.db.commit()
        await self.cache.invalidate(f"job:{job_id}:status")
        return job

    async def complete_job(
        self,
        job_id: UUID,
        agent_id: UUID,
        exit_code: int,
        stdout: str,
        stderr: str,
        duration_ms: int,
    ) -> JobResult:
        """Persist agent execution outcome into the matching JobResult row."""
        result = await self.db.execute(
            select(JobResult).where(
                JobResult.job_id == job_id,
                JobResult.agent_id == agent_id,
            )
        )
        job_result = result.scalar_one_or_none()
        if not job_result:
            raise ValueError(f"JobResult not found for job={job_id} agent={agent_id}")

        job_result.status = "COMPLETED" if exit_code == 0 else "FAILED"
        job_result.exit_code = exit_code
        job_result.stdout = stdout[:50000]   # cap at 50 KB
        job_result.stderr = stderr[:10000]   # cap at 10 KB
        job_result.duration_seconds = duration_ms // 1000
        job_result.completed_at = datetime.now(timezone.utc)

        await recompute_job_status(self.db, job_id)

        await self.db.commit()
        await self.cache.invalidate(f"job:{job_id}:status")
        return job_result
