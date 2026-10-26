"""
LokiLinux — JobService: job creation with dedup, result persistence.

Job targets agents via target_servers JSONB — there is no single agent_id FK on Job.
Per-agent execution state lives in JobResult (agent_id FK required).
"""

import hashlib
import json
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.cache import RedisCache
from lokilinux.models.agent import Agent
from lokilinux.models.approval import ApprovalClaim
from lokilinux.models.drift import DriftEvent
from lokilinux.models.job import Job, JobResult, JobStatus
from lokilinux.models.plugin import Plugin, PluginInstallation, PluginStatus
from lokilinux.models.remediation import RemediationAction, RemediationJob, RemediationPlan
from lokilinux.nats_topics import JOB_CREATED
from lokilinux.services.job_envelope import required_capabilities
from lokilinux.utils.capability_rbac import assert_no_smuggled_command

# Job types that execute arbitrary code as root on agents. These always
# require approval before an agent may pick them up — enforced here so the
# invariant holds for every caller (router, playbooks, policies, plugins).
_FORCE_APPROVAL_JOB_TYPES = frozenset({"CUSTOM_COMMAND", "ANSIBLE_PLAYBOOK"})

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

    if job.job_type == "COMPLIANCE_REMEDIATE":
        await _sync_remediation_plan(db, job)


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


async def _sync_remediation_plan(db: AsyncSession, job: Job) -> None:
    """Propagate terminal COMPLIANCE_REMEDIATE job status to the linked
    RemediationPlan. Idempotent — does not downgrade an already-ROLLED_BACK plan.

    Only acts when the job is terminal (COMPLETED/FAILED/TIMEOUT/CANCELLED).
    Uses the most recent RemediationJob link for this plan to avoid stale
    results from an earlier job overwriting a newer rollback.

    DRY_RUN jobs never touch plan.status — a dry-run result is informational,
    the plan stays in whatever state it was (docs/compliance §13).
    """
    if job.status not in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.TIMEOUT, JobStatus.CANCELLED):
        return

    operation = (job.parameters or {}).get("operation", "APPLY")
    if operation == "DRY_RUN":
        return

    plan_id_raw = (job.parameters or {}).get("remediation_plan_id")
    if not plan_id_raw:
        return
    plan_id = UUID(plan_id_raw)

    # Find the most recent job linked to this plan
    latest_link = (
        await db.execute(
            select(RemediationJob)
            .join(Job, Job.id == RemediationJob.job_id)
            .where(RemediationJob.remediation_plan_id == plan_id)
            .order_by(Job.created_at.desc())
        )
    ).scalars().first()

    if latest_link is None or latest_link.job_id != job.id:
        return  # a newer job exists for this plan — ignore stale results

    plan = await db.get(RemediationPlan, plan_id)
    if plan is None:
        return

    # Determine target status based on operation and job outcome
    if operation == "ROLLBACK":
        if job.status == JobStatus.COMPLETED:
            plan.status = "ROLLED_BACK"
        else:
            plan.status = "FAILED"
        # Plan U6/incident wiring: either way the fix is gone (undone, or
        # never landed) — the drift this plan was addressing is still real.
        await _revert_drift_to_open(db, plan_id)
    else:  # APPLY
        if job.status != JobStatus.COMPLETED:
            plan.status = "FAILED"
            await _revert_drift_to_open(db, plan_id)
        elif await _plan_has_verifiable_actions(db, plan_id):
            # The agent's exit code only means the commands ran without
            # error — not that the desired state actually holds
            # (docs/compliance §14: never mark successful on exit code
            # alone). RemediationVerificationWorker re-checks each action's
            # rule against a fresh post-apply evaluation before COMPLETED.
            plan.status = "VERIFYING"
        else:
            # No rule_id on any action — nothing to verify against, so the
            # old exit-code-based COMPLETED is the honest answer here.
            plan.status = "COMPLETED"


async def _revert_drift_to_open(db: AsyncSession, plan_id: UUID) -> None:
    """Plan U6/incident wiring counterpart to _dispatch's EXECUTING ->
    IN_REMEDIATION: a failed apply or a completed rollback means whatever
    this plan was fixing is unfixed again — only ever moves a drift_event
    this plan itself put into IN_REMEDIATION, never a state some other
    actor (ack/suppress/a different plan) already changed it to."""
    drift_event_ids = (
        (
            await db.execute(
                select(RemediationAction.drift_event_id).where(
                    RemediationAction.remediation_plan_id == plan_id,
                    RemediationAction.drift_event_id.isnot(None),
                )
            )
        )
        .scalars()
        .all()
    )
    if not drift_event_ids:
        return
    await db.execute(
        update(DriftEvent)
        .where(DriftEvent.id.in_(drift_event_ids), DriftEvent.status == "IN_REMEDIATION")
        .values(status="OPEN", last_seen=datetime.now(timezone.utc))
    )


async def _plan_has_verifiable_actions(db: AsyncSession, plan_id: UUID) -> bool:
    from lokilinux.models.remediation import RemediationAction

    row = (
        await db.execute(
            select(RemediationAction.id)
            .where(RemediationAction.remediation_plan_id == plan_id, RemediationAction.rule_id.isnot(None))
            .limit(1)
        )
    ).first()
    return row is not None


async def sync_remediation_plan(db: AsyncSession, job_id: UUID) -> None:
    """Public wrapper — call from job_timeout sweep and cancel_job after
    they mark a job terminal without going through recompute_job_status."""
    job = await db.get(Job, job_id)
    if job and job.job_type == "COMPLIANCE_REMEDIATE":
        await _sync_remediation_plan(db, job)


def parameters_for_agent(job, agent_id) -> dict:
    """The parameters one agent is sent. For COMPLIANCE_REMEDIATE that is only
    this agent's actions, so the approval claim must hash the same view
    (claim.job_hash is checked against exactly what the agent receives)."""
    params = job.parameters or {}
    if job.job_type != "COMPLIANCE_REMEDIATE":
        return params

    actions_map = params.get("actions", {})
    agent_actions = actions_map.get(str(agent_id), [])

    return {
        "remediation_plan_id": params.get("remediation_plan_id"),
        "operation": params.get("operation"),
        "actions": agent_actions,
    }


def _target_agent_uuids(target_servers) -> list[UUID]:
    """Agent PK UUIDs a job targets. target_servers arrives as {"<uuid>": true}
    from the dashboard checkbox map; older callers pass a list or {"agent_ids":[...]}."""
    if isinstance(target_servers, dict):
        ids = target_servers.get("agent_ids") or [k for k, v in target_servers.items() if v]
        return [UUID(a) for a in ids]
    if isinstance(target_servers, list):
        return [UUID(a) for a in target_servers]
    return []


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
        description=None,
        scheduled_time: datetime | None = None,
        policy_id: UUID | None = None,
        created_by: UUID | None = None,
        requires_approval: bool = False,
        skip_approval_gate: bool = False,
        created_by_actor: str | None = None,
    ) -> Job:
        """Create a job; raise ValueError on active duplicate.

        Fans out a JobResult(status=PENDING) row per target agent — this is
        what makes the job visible to AgentService.get_pending_jobs().

        Security invariant (docs/security/SECURITY_AUDIT.md CR-01):
        host-mutating jobs execute arbitrary code as root on agents and can
        never skip the approval gate. The ONLY exception is the workflow
        engine's dispatch path, whose `approval` node already applied an
        explicit, audited human gate upstream (skip_approval_gate=True) — a
        second hidden gate there would silently stall runs with no UI for it.
        """
        if job_type in _FORCE_APPROVAL_JOB_TYPES and not skip_approval_gate:
            requires_approval = True
        params = parameters or {}
        # A `command` parameter on a job type that is not a shell job would be
        # executed as root by the agent's generic dispatch branch, bypassing the
        # EXEC_BASH capability gate. Enforced here — the single chokepoint
        # every job creation path (router, policies, workflows, services)
        # routes through.
        assert_no_smuggled_command(job_type, params)
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

        agent_uuids = _target_agent_uuids(target_servers)

        job = Job(
            name=name,
            job_type=job_type,
            description=description,
            target_servers=target_servers,
            parameters=params,
            scheduled_time=scheduled_time,
            policy_id=policy_id,
            created_by=created_by,
            created_by_actor=created_by_actor,
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

    async def approve_job(
        self, job_id: UUID, approved_by: UUID | None, approver_actor: str | None = None
    ) -> Job:
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
        # Four-eyes: the requester cannot approve their own job. Both forms are checked:
        # created_by_actor covers nanoid requesters, created_by the rows written before it.
        if (approver_actor and job.created_by_actor == approver_actor) or (
            job.created_by is not None and job.created_by == approved_by
        ):
            raise ValueError("Job creator cannot approve their own job")

        job.approved_by = approved_by
        job.approved_at = datetime.now(timezone.utc)

        # Issue the signed approval claim (plan §6). Signing is best-effort at
        # this layer: without a provisioned key the DB approval still stands,
        # but agents in enforcement mode will reject execution — surfaced via
        # metrics rather than blocking the administrative action here.
        claim_json = None
        try:
            signer = _get_job_signer()
            if signer is not None:
                # The claim names CAPABILITIES, not job types: the agent
                # checks the claim against the envelope's
                # requested_capabilities (agent/internal/security/
                # approval_claim.go), and both come from the same registry.
                # Signing the job type here made every approved job
                # fail with claim_missing_caps:<CAPABILITY>.
                capabilities = required_capabilities(job.job_type, job.parameters or {})
                # One claim per target: each agent rejects a claim whose target is
                # not its own. The agent checks claim.target_agent_id against its
                # wire agent_id (Agent.agent_id), not the Agent PK in target_servers.
                for aid in _target_agent_uuids(job.target_servers):
                    target_row = await self.db.get(Agent, aid)
                    target_agent = target_row.agent_id if target_row else ""
                    claim = signer.sign_approval_claim(
                        job_id=str(job.id),
                        target_agent_id=target_agent,
                        payload=parameters_for_agent(job, aid),
                        capabilities=capabilities,
                        approver_id=str(approved_by) if approved_by else "",
                    )
                    self.db.add(ApprovalClaim(
                        job_id=job.id,
                        approver_id=str(approved_by) if approved_by else None,
                        target_agent_id=target_agent,
                        claim_json=json.dumps(claim),
                        expires_at=datetime.fromtimestamp(claim["expires_at"], tz=timezone.utc),
                    ))
                    if claim_json is None:
                        claim_json = json.dumps(claim)  # first target's claim, for existing callers
        except Exception:  # noqa: BLE001 — approval must not fail for signing infra
            import logging

            logging.getLogger(__name__).exception("approval claim issuance failed")

        await self.db.commit()
        await self.cache.invalidate(f"job:{job_id}:status")
        job.approval_claim_json = claim_json  # transient, not a column
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


def _get_job_signer():
    """Lazy JobSigner; None when unprovisioned. Same layout choice as
    job_envelope._get_signer: with LOKILINUX_KEYS_DIR, signing uses the ACTIVE
    key version (v1 bootstrapped from the legacy file); without it the legacy
    single file is implicit v1."""
    try:
        import os

        from lokilinux.kms import KeyManager, get_provider
        from lokilinux.services.job_envelope import _bootstrap_versioned_key
        from lokilinux.services.job_signing import JobSigner

        keys_dir = os.environ.get("LOKILINUX_KEYS_DIR", "")
        if not keys_dir:
            return JobSigner()
        key_path = os.environ.get("JOB_SIGNING_KEY_PATH", "/etc/lokilinux/certs/job_signing.key")
        provider = get_provider({"provider": "file", "file": {"key_path": key_path}})
        _bootstrap_versioned_key(KeyManager(keys_dir, "job-signing"), key_path)
        return JobSigner(provider=provider, keys_dir=keys_dir)
    except Exception:  # noqa: BLE001 — no key installed yet
        return None
