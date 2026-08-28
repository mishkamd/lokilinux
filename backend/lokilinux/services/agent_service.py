"""
LokiLinux — AgentService: heartbeat updates, pending-job dispatch, inactivity marking.
"""

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import and_, case, delete, or_, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.cache import RedisCache
from lokilinux.models.agent import Agent, AgentStatus
from lokilinux.models.agent import AgentHealth as AgentHealthRow
from lokilinux.models.cve import CVE, AgentVulnerability, Package
from lokilinux.models.job import JobResult
from lokilinux.services.alert_service import AlertService
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
        was_active = agent.status == AgentStatus.ACTIVE
        agent.last_heartbeat = datetime.now(timezone.utc)
        agent.status = AgentStatus.ACTIVE
        if not was_active:
            # Recovery transition only — checking this on every heartbeat
            # would mean a query per agent per 60s in steady state for
            # nothing. Without this, nothing ever closes an AGENT_OFFLINE
            # alert: confirmed live, both fleet agents were healthy and
            # heartbeating but still carried 68 ACTIVE alerts between them.
            await AlertService(self.db).resolve_agent_offline_alerts(agent.id)
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

        vulnerabilities = data.get("vulnerabilities")
        if vulnerabilities is not None:
            # sendHeartbeat (agent/internal/agent/manager.go) always computes
            # vulns := Vulnerabilities(pkgs) from whatever ListPackages() just
            # returned — including a transient failure, where pkgs is empty
            # and vulns is therefore empty too, indistinguishable at this
            # layer from "real scan, host fully patched". Use `packages`
            # non-empty as proof this heartbeat's collection actually
            # succeeded before trusting an empty vulnerabilities list enough
            # to reconcile (mark prior findings resolved) on it.
            await self._sync_vulnerabilities(agent.id, vulnerabilities, scan_succeeded=bool(packages))

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
        """Upsert the agent's reported package list, then reconcile: drop any
        stored (name, version) row for this agent that the report no longer
        contains.

        The unique constraint is (agent_id, name, version) — an upgrade from
        1.0 to 1.1 inserts a *new* row for 1.1 and, without this reconcile
        step, leaves the 1.0 row behind forever (there's no "uninstalled"
        signal otherwise). Confirmed live: kernel/gpg-pubkey each had 3-4
        stale rows after enough upgrades. Packages genuinely installed
        multiple times at once (e.g. several kernel versions) are unaffected
        — they're all in the current report, so none of their rows match the
        delete condition.
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

        reported = [(r["name"], r["version"]) for r in rows]
        await self.db.execute(
            delete(Package).where(
                Package.agent_id == agent_pk,
                tuple_(Package.name, Package.version).not_in(reported),
            )
        )
        await self.db.commit()

    async def _sync_vulnerabilities(
        self, agent_pk: UUID, vulnerabilities: list[dict], *, scan_succeeded: bool
    ) -> None:
        """Upsert the agent's reported CVEs, then reconcile: any previously
        non-remediated (cve_id, package_name) for this agent that the new
        report no longer contains gets marked remediated (not deleted — the
        whole point of is_remediated/remediation_date is to keep a record of
        what got fixed and when, same reasoning as _sync_packages next to it
        but with history preserved instead of the row dropped).

        cves is upserted first: agent_vulnerabilities.cve_id has an FK to
        cves.cve_id, so a row must exist there before it can be referenced.
        Distro advisory metadata only gives us cve_id + severity — title,
        description, cvss_v3_score, published_date stay NULL rather than
        being invented.

        An empty `vulnerabilities` list is the normal steady state once
        everything's patched — it must still run the reconcile step below
        (mark everything remediated), not bail out early the way
        _sync_packages does. BUT the agent's sendHeartbeat computes
        vulnerabilities from whatever ListPackages() just returned on every
        heartbeat unconditionally, including a transient failure — a failed
        package listing and a genuinely clean host both arrive here as an
        empty list, with nothing in this payload alone to tell them apart.
        `scan_succeeded` (the caller's `bool(data.get("packages"))`) is that
        signal: reconcile only runs when this heartbeat's package listing
        actually produced something, so a transient collector hiccup can
        never be misread as "everything got patched" and silently resolve a
        host's real, still-open vulnerabilities.
        """
        rows = [
            {
                "cve_id": v["cve_id"],
                "package_name": v["package_name"],
                "package_version": v.get("installed_version") or "",
                "severity": v.get("severity") or None,
                "fixed_version": v.get("fixed_version") or None,
            }
            for v in vulnerabilities
            if v.get("cve_id") and v.get("package_name")
        ]

        if rows:
            # One CVE routinely affects several packages in the same heartbeat
            # (e.g. one kernel advisory across kernel/kernel-core/kernel-
            # modules/...) — the cves upsert's conflict target is cve_id
            # alone, so duplicate cve_ids in the same INSERT..VALUES trip
            # Postgres's "ON CONFLICT DO UPDATE command cannot affect row a
            # second time" (confirmed live). Dedupe by cve_id first; severity
            # is advisory-level, not package-level, so any one occurrence is
            # the same value.
            unique_cves = {r["cve_id"]: r["severity"] for r in rows}
            cve_stmt = pg_insert(CVE).values([
                {"cve_id": cve_id, "cvss_v3_severity": severity} for cve_id, severity in unique_cves.items()
            ])
            cve_stmt = cve_stmt.on_conflict_do_update(
                index_elements=["cve_id"],
                set_={"cvss_v3_severity": cve_stmt.excluded.cvss_v3_severity, "updated_at": datetime.now(timezone.utc)},
            )
            await self.db.execute(cve_stmt)

            # agent_vulnerabilities' conflict target is (agent_id, cve_id,
            # package_name) — dedupe the same way in case a source ever lists
            # the same CVE/package pair twice in one report.
            unique_vulns = {(r["cve_id"], r["package_name"]): r for r in rows}
            now = datetime.now(timezone.utc)
            vuln_stmt = pg_insert(AgentVulnerability).values([
                {
                    "agent_id": agent_pk,
                    "cve_id": r["cve_id"],
                    "package_name": r["package_name"],
                    "package_version": r["package_version"],
                    "severity": r["severity"],
                    "fixed_version": r["fixed_version"],
                    "fix_available": True,
                    "status": "PATCH_AVAILABLE",
                    "last_scan_at": now,
                }
                for r in unique_vulns.values()
            ])
            vuln_stmt = vuln_stmt.on_conflict_do_update(
                constraint="uq_agent_vuln_agent_cve_package",
                set_={
                    "package_version": vuln_stmt.excluded.package_version,
                    "severity": vuln_stmt.excluded.severity,
                    "fixed_version": vuln_stmt.excluded.fixed_version,
                    "last_check": now,
                    "last_scan_at": now,
                    # A re-detected CVE reopens OPEN/RESOLVED findings (a
                    # previous remediation didn't stick, or a downgrade
                    # reintroduced it) but never overwrites a status someone
                    # is actively working — IN_PROGRESS/MITIGATED/
                    # ACCEPTED_RISK stay exactly as a human/process left them.
                    "status": case(
                        (AgentVulnerability.status.in_(("IN_PROGRESS", "MITIGATED", "ACCEPTED_RISK")), AgentVulnerability.status),
                        else_="PATCH_AVAILABLE",
                    ),
                    # Re-detected means present again, i.e. by definition not
                    # remediated — true in every branch above, including the
                    # protected ones (IN_PROGRESS/MITIGATED/ACCEPTED_RISK
                    # were never is_remediated=True to begin with).
                    "is_remediated": False,
                    # Clear a stale resolved-date from a prior remediation
                    # cycle — otherwise vulnerability_counts_by_day's
                    # discovered_at/remediation_date reconstruction reads a
                    # reopened finding as still closed on today's date
                    # (confirmed live: 38/100 open findings had this).
                    "remediation_date": None,
                },
            )
            await self.db.execute(vuln_stmt)

        if scan_succeeded:
            reported = [(r["cve_id"], r["package_name"]) for r in rows]
            await self.db.execute(
                update(AgentVulnerability)
                .where(
                    AgentVulnerability.agent_id == agent_pk,
                    AgentVulnerability.is_remediated.is_(False),
                    tuple_(AgentVulnerability.cve_id, AgentVulnerability.package_name).not_in(reported),
                )
                .values(
                    is_remediated=True,
                    status="RESOLVED",
                    remediation_date=datetime.now(timezone.utc),
                )
            )
        await self.db.commit()

        # invalidate_agent (called unconditionally at the end of
        # update_heartbeat) only clears this agent's own vulnerability:*
        # cache — the *global* /vulnerabilities list is cached under cve:*
        # and would otherwise keep serving a stale (e.g. pre-existing empty)
        # response for up to TTL_CVE_DATA after this agent's first real
        # report. Confirmed live: a cve:list:... key cached empty before any
        # agent had reported CVEs kept the global page blank for an hour
        # after real data landed.
        await self.cache.invalidate_cve_database()

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

            # Audit fields (agent-security-hardening plan P10) — reuses the
            # otherwise-unused resources_used JSONB column rather than a new
            # migration; only present when the agent actually populated them
            # (capability/risk from a known job_type, policy_id from a
            # signed envelope — see manager.go's populateAuditFields).
            audit_meta = {
                k: r.get(k)
                for k in ("capability", "risk_level", "policy_id", "duration_ms")
                if r.get(k)
            }
            if audit_meta:
                row.resources_used = audit_meta

            touched_job_ids.add(UUID(job_id))

        for jid in touched_job_ids:
            await recompute_job_status(self.db, jid)

        await self.db.commit()

        for jid in touched_job_ids:
            await self.cache.invalidate(f"job:{jid}:status")
        if touched_job_ids:
            await self.cache.invalidate_pattern("job:list:*")

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

            for jid in job_ids:
                await self.cache.invalidate(f"job:{jid}:status")
            await self.cache.invalidate_pattern("job:list:*")

        return jobs

    async def mark_inactive(self, agent_id: UUID) -> None:
        """Mark agent INACTIVE (called by a background stale-check task)."""
        await self.db.execute(
            update(Agent)
            .where(Agent.id == agent_id)
            .values(status=AgentStatus.INACTIVE)
        )
        await self.db.commit()
