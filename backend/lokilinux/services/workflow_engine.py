"""
LokiLinux — WorkflowEngine: advances a WorkflowRun by translating ready
steps into Jobs and reading their results back.

Containment principle (plan §3, mirrors RemediationService): this module
never talks to an agent. It only creates Jobs via JobService/PlaybookService
and reads Job.status — exactly the same boundary RemediationService already
draws around the Job Engine.

Partea III of the migration plan — Compile-Down Rule: a Linux/Check node
(`service`/`system`/`file`/`check`, plus `package`'s remove/downgrade
actions) declares INTENT (an `action` or `type` discriminant plus
parameters), never a shell string. Translation into an actual `CUSTOM_COMMAND`
Job happens exclusively in `_compile_*` below, using `utils.shell.q` for
every interpolated value — the workflow YAML stays stable even if the
target of the compilation later moves from shell to a native agent module
(Phase 10), and it stays safe (a service *named* `nginx; rm -rf /` becomes
one harmless quoted argument, never a second command).

`command`/`ansible` create Jobs directly (no compilation — the user already
wrote the shell/playbook). `package`'s install/update actions dispatch the
NATIVE `PACKAGE_UPDATE` job type (agent/internal/modules/package_updater.go)
rather than compiling to shell, since that module already exists and is
version/manager-aware. `start`/`end`/`condition`/`approval`/`wait`/
`notification`/`webhook` never create a Job at all — see advance_run's
ready-loop. `notification` calls AlertService.create_alert directly (the
`nats` client threaded through advance_run/start_run/approve_step from
main.py/the router is what lets NotificationWorker actually deliver it —
without it the Alert row is created but nothing gets emailed/Slacked, see
_dispatch_notification). `webhook` POSTs synchronously via httpx.

VALIDATION and WAIT_FOR_AGENT are permanent legacy aliases (see
schemas/workflow.py's WorkflowNodeType docstring) — `_normalize_type` below
maps them to CHECK/WAIT before any dispatch decision, so every function
past that point only ever sees the 14 canonical types.

advance_run is called from two places: once synchronously right after
start_run (so a manual "Run" feels responsive, not "wait up to 5s for the
next tick"), and by WorkflowRunnerWorker's tick (workers/workflow_runner.py)
for everything after that.
"""

import hashlib
from datetime import datetime, timezone
from uuid import UUID

import httpx
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.cache import RedisCache
from lokilinux.models.agent import Agent
from lokilinux.models.job import Job, JobStatus
from lokilinux.models.workflow import Workflow, WorkflowRun, WorkflowStepRun, WorkflowVersion
from lokilinux.object_storage import ObjectStorage
from lokilinux.schemas.workflow import (
    CompiledGraph,
    DryRunResponse,
    DryRunStepResult,
    WorkflowNodeType,
    WorkflowStep,
)
from lokilinux.services.alert_service import AlertService
from lokilinux.services.audit_service import AuditService
from lokilinux.services.job_service import JobService
from lokilinux.services.playbook_service import PlaybookService
from lokilinux.services.policy_service import resolve_targets
from lokilinux.utils.agent_capability import agent_meets_minimum
from lokilinux.utils.expr import ExpressionError, evaluate_condition
from lokilinux.utils.shell import q

_TERMINAL_JOB_SUCCESS = JobStatus.COMPLETED
_TERMINAL_JOB_STATUSES = (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.TIMEOUT, JobStatus.CANCELLED)
_CANCELLABLE_JOB_STATUSES = (JobStatus.QUEUED, JobStatus.SCHEDULED)

# Legacy alias -> canonical type. Applied once, everywhere, via
# _normalize_type — nothing past that point ever compares against
# VALIDATION/WAIT_FOR_AGENT directly again.
_ALIASES = {
    WorkflowNodeType.VALIDATION: WorkflowNodeType.CHECK,
    WorkflowNodeType.WAIT_FOR_AGENT: WorkflowNodeType.WAIT,
}

# Types the ready-loop in advance_run handles inline (no Job at all — see
# each branch/`_dispatch_*` docstring for what each one actually does).
_INLINE_TYPES = (
    WorkflowNodeType.START, WorkflowNodeType.END, WorkflowNodeType.APPROVAL,
    WorkflowNodeType.CONDITION, WorkflowNodeType.WAIT,
    WorkflowNodeType.NOTIFICATION, WorkflowNodeType.WEBHOOK,
)

# Every registry type now has a real dispatch path (Etapa 4 wired
# notification/webhook) — kept as an extension point for a future type
# that's declared before its execution path lands.
_NOT_YET_EXECUTABLE: tuple[WorkflowNodeType, ...] = ()

# Confirmed default agent heartbeat interval (agent/internal/agent/manager_test.go:17)
# — the job dispatch path is agent-pull-on-heartbeat (agent_service.py:385-446),
# so this is the real per-step floor. Shown to the user in dry-run rather
# than hidden (plan §12 / PRODUCT.md: "heartbeat latency surfaced honestly").
_HEARTBEAT_INTERVAL_SECONDS = 60


def _normalize_type(node_type: WorkflowNodeType) -> WorkflowNodeType:
    return _ALIASES.get(node_type, node_type)


def _require(config: dict, key: str, step_id: str) -> str:
    value = config.get(key)
    if value is None or value == "":
        raise WorkflowRunError(f"step '{step_id}': config.{key} is required")
    return str(value)


class WorkflowRunError(Exception):
    """Raised for a run-level problem that isn't a single step's fault
    (missing version, corrupt graph) — the caller decides whether that's an
    HTTP 4xx (API path) or a logged skip (worker tick path)."""


async def _get_workflow(db: AsyncSession, workflow_id: UUID) -> Workflow:
    row = (await db.execute(select(Workflow).where(Workflow.id == workflow_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return row


async def _get_run(db: AsyncSession, run_id: UUID) -> WorkflowRun:
    row = (await db.execute(select(WorkflowRun).where(WorkflowRun.id == run_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Workflow run not found")
    return row


async def _load_step_runs(db: AsyncSession, run_id: UUID) -> dict[str, WorkflowStepRun]:
    rows = (await db.execute(select(WorkflowStepRun).where(WorkflowStepRun.run_id == run_id))).scalars().all()
    return {sr.step_id: sr for sr in rows}


async def start_run(
    db: AsyncSession, cache: RedisCache, storage: ObjectStorage, workflow_id: UUID, *,
    trigger_type: str, triggered_by: UUID | None, is_dry_run: bool = False, nats=None,
) -> WorkflowRun:
    workflow = await _get_workflow(db, workflow_id)
    if workflow.current_version_id is None:
        raise HTTPException(status_code=409, detail="Workflow has no published version")

    version = (await db.execute(
        select(WorkflowVersion).where(WorkflowVersion.id == workflow.current_version_id)
    )).scalar_one_or_none()
    if version is None or version.status != "PUBLISHED":
        raise HTTPException(status_code=409, detail="Workflow's current version is not published")

    graph = CompiledGraph.model_validate(version.graph)

    # Targets resolved ONCE and frozen — a server added mid-run must not
    # silently receive only the remaining steps (plan §4).
    target_agent_ids = await resolve_targets(db, graph.targets.model_dump(mode="json", exclude_none=True))
    if not target_agent_ids:
        raise HTTPException(status_code=422, detail="No agents match this workflow's targets")

    run = WorkflowRun(
        workflow_id=workflow.id, workflow_version_id=version.id,
        status="RUNNING", trigger_type=trigger_type, triggered_by=triggered_by,
        targets={"agent_ids": [str(a) for a in target_agent_ids]},
        vars=graph.vars, is_dry_run=is_dry_run, started_at=datetime.now(timezone.utc),
    )
    db.add(run)
    await db.flush()

    for step in graph.steps:
        db.add(WorkflowStepRun(run_id=run.id, step_id=step.id, status="PENDING"))

    await db.commit()
    await AuditService(db).log(
        action="workflow.run_started", user_id=str(triggered_by) if triggered_by else None,
        resource_type="workflow_run", resource_id=str(run.id),
        changes={"workflow_id": str(workflow.id), "trigger_type": trigger_type},
    )

    if not is_dry_run:
        await advance_run(db, cache, storage, run, nats)
    return run


async def dry_run(db: AsyncSession, workflow_id: UUID) -> DryRunResponse:
    """Stateless preview (plan §11/§12) — resolves targets and reports the
    execution plan without creating a WorkflowRun or any Job. Distinct from
    `start_run(..., is_dry_run=True)`, which *does* persist a run (useful
    for testing the graph's own advancement logic) but creates no Jobs
    either — this function creates nothing at all.

    "Blocked" here means honestly binary — a step type this engine can't
    execute yet (Phase 7/10) — not a fabricated per-agent eligibility check
    (disk space, repo reachability) the system has no real data for."""
    workflow = await _get_workflow(db, workflow_id)
    if workflow.current_version_id is None:
        raise HTTPException(status_code=409, detail="Workflow has no published version")

    version = (await db.execute(
        select(WorkflowVersion).where(WorkflowVersion.id == workflow.current_version_id)
    )).scalar_one_or_none()
    if version is None:
        raise HTTPException(status_code=409, detail="Workflow's current version could not be loaded")

    graph = CompiledGraph.model_validate(version.graph)
    target_agent_ids = await resolve_targets(db, graph.targets.model_dump(mode="json", exclude_none=True))
    matched = len(target_agent_ids)

    # Dispatch-time estimate: start/end/condition/approval evaluate
    # synchronously (no heartbeat wait), so they contribute 0 — a flat
    # per-step heartbeat unit would overstate the honest estimate this
    # function exists to give. wait genuinely costs real wall-clock time,
    # but a config-dependent amount, not one heartbeat — its own
    # min_heartbeats/seconds is used instead of the flat unit. Everything
    # else compiles to a Job (Partea III's Compile-Down Rule) and costs one
    # heartbeat, same as command/ansible always did.
    steps: list[DryRunStepResult] = []
    estimated_seconds = 0
    for step in graph.steps:
        normalized = _normalize_type(step.type)
        executable = normalized not in _NOT_YET_EXECUTABLE
        if normalized in (
            WorkflowNodeType.START, WorkflowNodeType.END, WorkflowNodeType.CONDITION, WorkflowNodeType.APPROVAL,
            WorkflowNodeType.NOTIFICATION, WorkflowNodeType.WEBHOOK,
        ):
            pass
        elif normalized == WorkflowNodeType.WAIT:
            config = step.config or {}
            if (config.get("mode") or "agent") == "duration":
                estimated_seconds += int(config.get("seconds") or 0)
            else:
                estimated_seconds += int(config.get("min_heartbeats") or 1) * _HEARTBEAT_INTERVAL_SECONDS
        elif executable:
            estimated_seconds += _HEARTBEAT_INTERVAL_SECONDS
        if executable:
            steps.append(DryRunStepResult(id=step.id, type=step.type.value, eligible=matched, blocked=0))
        else:
            steps.append(DryRunStepResult(
                id=step.id, type=step.type.value, eligible=0, blocked=matched,
                reasons={"step_type_not_executable_yet": matched},
            ))

    return DryRunResponse(
        targets_matched=matched,
        targets=target_agent_ids,
        steps=steps,
        estimated_dispatch_seconds=estimated_seconds,
        requires_approval_at=[s.id for s in graph.steps if s.type == WorkflowNodeType.APPROVAL],
    )


def _incoming_edges(graph: CompiledGraph, step_id: str) -> list:
    return [e for e in graph.edges if e.to == step_id]


async def _agents_support_native(db: AsyncSession, target_agent_ids: list[UUID]) -> bool:
    """True only when every target agent's agent_version meets the minimum
    Faza 10's native modules shipped in — see utils/agent_capability.py's
    docstring for why this exists instead of real capability negotiation.
    A Job's job_type is uniform across every JobResult it fans out to,
    so one target agent below the minimum routes the WHOLE Job through
    compile-down, not a per-agent split."""
    if not target_agent_ids:
        return False
    versions = (await db.execute(select(Agent.agent_version).where(Agent.id.in_(target_agent_ids)))).scalars().all()
    return len(versions) == len(target_agent_ids) and all(agent_meets_minimum(v) for v in versions)


_CHECK_STATE_FLAG = {"exists": "-e", "file": "-f", "directory": "-d"}
_SERVICE_ACTIONS = ("start", "stop", "restart", "reload", "enable", "disable")


def _compile_check(step: WorkflowStep) -> str:
    """CHECK (and legacy VALIDATION, the type='command' default variant —
    its flat `{command, expect_exit_code}` shape IS type='command')."""
    config = step.config or {}
    check_type = config.get("type") or "command"

    if check_type == "command":
        base = _require(config, "command", step.id)
    elif check_type == "service":
        base = f"systemctl is-active {q(_require(config, 'service', step.id))}"
    elif check_type == "port":
        host = config.get("host") or "localhost"
        port = int(_require(config, "port", step.id))
        base = f"timeout 2 bash -c '</dev/tcp/{host}/{port}'"
    elif check_type == "package":
        name = q(_require(config, "name", step.id))
        base = f"(command -v rpm >/dev/null 2>&1 && rpm -q {name}) || dpkg -s {name}"
    elif check_type == "file":
        flag = _CHECK_STATE_FLAG.get(config.get("state") or "exists", "-e")
        base = f"test {flag} {q(_require(config, 'path', step.id))}"
    elif check_type == "process":
        base = f"pgrep -x {q(_require(config, 'name', step.id))}"
    elif check_type == "os":
        pattern = f"{_require(config, 'distro', step.id)} {config.get('version') or ''}".strip()
        base = f"grep -q {q(pattern)} /etc/os-release"
    elif check_type == "disk":
        path = config.get("path") or "/"
        min_free = int(_require(config, "min_free_gb", step.id))
        base = f"[ $(df --output=avail -BG {q(path)} | tail -1 | tr -dc '0-9') -ge {min_free} ]"
    elif check_type == "network":
        base = f"ping -c1 -W2 {q(_require(config, 'host', step.id))}"
    else:
        raise WorkflowRunError(f"step '{step.id}': check type '{check_type}' is not supported")

    expect = config.get("expect_exit_code")
    return f"{base}; test $? -eq {int(expect)}" if expect is not None else base


def _compile_service(step: WorkflowStep) -> str:
    config = step.config or {}
    action = config.get("action")
    if action not in _SERVICE_ACTIONS:
        raise WorkflowRunError(f"step '{step.id}' (type service): action '{action}' is not one of {_SERVICE_ACTIONS}")
    return f"systemctl {action} {q(_require(config, 'name', step.id))}"


def _compile_system(step: WorkflowStep) -> str:
    """Reboot/shutdown use the same deferred-execution trick the old Reboot
    preset used: `systemd-run --on-active=Ns` lets the agent report
    COMPLETED before the machine actually goes down, instead of the Job
    hanging until JobTimeoutWorker kills it."""
    config = step.config or {}
    action = config.get("action")
    if action == "reboot":
        return f"systemd-run --on-active={int(config.get('delay_seconds') or 5)}s systemctl reboot"
    if action == "shutdown":
        return f"systemd-run --on-active={int(config.get('delay_seconds') or 5)}s systemctl poweroff"
    if action == "hostname":
        return f"hostnamectl set-hostname {q(_require(config, 'value', step.id))}"
    if action == "timezone":
        return f"timedatectl set-timezone {q(_require(config, 'value', step.id))}"
    if action == "sysctl":
        return f"sysctl -w {q(_require(config, 'key', step.id))}={q(_require(config, 'value', step.id))}"
    raise WorkflowRunError(f"step '{step.id}' (type system): action '{action}' is not supported")


def _compile_file(step: WorkflowStep) -> str:
    config = step.config or {}
    action = config.get("action")
    path = q(_require(config, "path", step.id))

    if action in ("create", "template"):
        # v1: no template engine on the backend — `template` writes
        # `content` verbatim, same as `create`. Rendering (if ever needed)
        # belongs client-side, before this ever reaches the engine.
        content = q(config.get("content") or "")
        mode = config.get("mode")
        cmd = f"printf '%s' {content} > {path}"
        return f"{cmd} && chmod {q(mode)} {path}" if mode else cmd
    if action == "delete":
        return f"rm -f {path}"
    if action == "copy":
        return f"cp {q(_require(config, 'source', step.id))} {path}"
    if action == "chmod":
        return f"chmod {q(_require(config, 'mode', step.id))} {path}"
    if action == "chown":
        owner, group = config.get("owner") or "", config.get("group") or ""
        spec = f"{owner}:{group}" if group else owner
        if not spec:
            raise WorkflowRunError(f"step '{step.id}' (type file, action chown) needs config.owner and/or config.group")
        return f"chown {q(spec)} {path}"
    raise WorkflowRunError(f"step '{step.id}' (type file): action '{action}' is not supported")


def _compile_package_remove(step: WorkflowStep) -> str:
    config = step.config or {}
    packages = config.get("packages") or []
    if not packages:
        raise WorkflowRunError(f"step '{step.id}' (type package): config.packages is empty")
    names = " ".join(q(p) for p in packages)
    # OR-chained across the three package-manager families the agent
    # already targets (package_manager.go) — whichever binary exists wins;
    # none of the three no-ops silently if the packages aren't installed.
    return (
        f"(command -v dnf >/dev/null 2>&1 && dnf remove -y {names}) || "
        f"(command -v apt-get >/dev/null 2>&1 && apt-get remove -y {names}) || "
        f"(command -v zypper >/dev/null 2>&1 && zypper remove -y {names})"
    )


async def _dispatch_step(
    db: AsyncSession, cache: RedisCache, storage: ObjectStorage, step: WorkflowStep,
    target_agent_ids: list[UUID], run_id: UUID,
) -> Job:
    """Translate one workflow step into a Job. requires_approval is always
    False here — the workflow's own `approval` node type is the human gate;
    a second, hidden per-Job approval on top of it would silently stall the
    run with no UI pointing at why (see PlaybookService.execute_playbook's
    docstring). Called only for the "generic" step types — start/end/
    condition/approval/wait never reach here, see advance_run's ready-loop."""
    normalized = _normalize_type(step.type)
    config = step.config or {}
    target_servers = {"agent_ids": [str(a) for a in target_agent_ids]}
    extra_params = {"workflow_run_id": str(run_id), "workflow_step_id": step.id}

    if normalized == WorkflowNodeType.ANSIBLE:
        playbook_id = config.get("playbook_id")
        if not playbook_id:
            raise WorkflowRunError(f"step '{step.id}' (type ansible) has no config.playbook_id")
        return await PlaybookService(db, cache, storage).execute_playbook(
            playbook_id=UUID(str(playbook_id)),
            agent_ids=target_agent_ids,
            extra_vars=config.get("extra_vars") or {},
            extra_job_parameters=extra_params,
            requires_approval=False,
        )

    if normalized == WorkflowNodeType.PACKAGE:
        action = config.get("action") or "install"
        if action in ("install", "update"):
            # Native module (package_updater.go) — already version/manager-
            # aware, so this is the one Linux type that does NOT compile to
            # shell for its primary actions.
            return await JobService(db, cache).create_job(
                name=f"Workflow step: {step.name}", job_type="PACKAGE_UPDATE",
                target_servers=target_servers,
                parameters={"package_names": [str(p) for p in (config.get("packages") or [])], **extra_params},
                requires_approval=False,
            )
        if action == "remove":
            command = _compile_package_remove(step)
        else:
            # "downgrade": package manager syntax diverges too much across
            # dnf/apt/zypper for one generated line to be safe — refuses
            # rather than guessing (Honest Palette Rule).
            raise WorkflowRunError(f"step '{step.id}' (type package): action 'downgrade' is not supported yet")
    elif normalized == WorkflowNodeType.SERVICE:
        if await _agents_support_native(db, target_agent_ids):
            return await JobService(db, cache).create_job(
                name=f"Workflow step: {step.name}", job_type="SERVICE",
                target_servers=target_servers, parameters={**config, **extra_params},
                requires_approval=False,
            )
        command = _compile_service(step)
    elif normalized == WorkflowNodeType.SYSTEM:
        # Only reboot/shutdown have a native module (reboot.go) — hostname/
        # timezone/sysctl always compile to shell, at any agent version.
        if config.get("action") in ("reboot", "shutdown") and await _agents_support_native(db, target_agent_ids):
            return await JobService(db, cache).create_job(
                name=f"Workflow step: {step.name}", job_type="REBOOT",
                target_servers=target_servers, parameters={**config, **extra_params},
                requires_approval=False,
            )
        command = _compile_system(step)
    elif normalized == WorkflowNodeType.FILE:
        if await _agents_support_native(db, target_agent_ids):
            return await JobService(db, cache).create_job(
                name=f"Workflow step: {step.name}", job_type="FILE",
                target_servers=target_servers, parameters={**config, **extra_params},
                requires_approval=False,
            )
        command = _compile_file(step)
    elif normalized == WorkflowNodeType.CHECK:
        command = _compile_check(step)
    elif normalized == WorkflowNodeType.COMMAND:
        command = _require(config, "command", step.id)
    else:
        raise WorkflowRunError(f"step type '{step.type.value}' is not executable yet")

    return await JobService(db, cache).create_job(
        name=f"Workflow step: {step.name}", job_type="CUSTOM_COMMAND",
        target_servers=target_servers, parameters={"command": command, **extra_params},
        requires_approval=False,
        # CR-01 invariant exception: the workflow's approval node is the human
        # gate — see create_job's security-invariant docstring.
        skip_approval_gate=True,
    )


async def _dispatch_notification(db: AsyncSession, nats, step: WorkflowStep, run: WorkflowRun) -> None:
    """No Job — creates an Alert row directly via AlertService, exactly like
    every other alert source in the app. alert_type is scoped to this run+
    step (not just the channel/subject) so AlertService's ACTIVE-alert dedup
    — meant to stop a recurring condition from spamming, e.g. a flapping
    agent — never eats two distinct workflow runs' notifications. Without
    `nats` the Alert row still gets created (visible in /alerts) but nothing
    is actually emailed/Slacked — NotificationWorker only delivers on the
    lokilinux.alert.created event AlertService publishes."""
    config = step.config or {}
    # alert_type is String(100) — a raw f"{run.id}:{step.id}" can exceed that
    # once step ids get close to their 64-char max, so it's hashed down to a
    # short, still-unique-per-run-per-step token instead of truncated.
    digest = hashlib.sha256(f"{run.id}:{step.id}".encode()).hexdigest()[:16]
    alert_type = f"WORKFLOW_STEP:{digest}"
    alert = await AlertService(db, nats).create_alert(
        title=str(config.get("subject") or step.name),
        description=str(config.get("message") or f"Workflow step '{step.name}' reached."),
        severity="LOW",
        alert_type=alert_type,
    )
    if alert is None:
        raise WorkflowRunError(f"step '{step.id}': an ACTIVE alert with type '{alert_type}' already exists")


async def _dispatch_webhook(step: WorkflowStep) -> None:
    """No Job — POSTs synchronously and raises on a non-2xx/network error so
    the step run fails cleanly instead of reporting success for a request
    nobody received."""
    config = step.config or {}
    url = _require(config, "url", step.id)
    method = str(config.get("method") or "POST").upper()
    timeout = float(config.get("timeout") or 10)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.request(method, url, headers=config.get("headers") or None, json=config.get("body") or None)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise WorkflowRunError(f"step '{step.id}' (type webhook): request failed: {exc}") from exc


async def _step_exit_code(db: AsyncSession, job_id) -> int | None:
    """Best-effort single exit_code for a fleet-wide step's Job — exposed to
    condition expressions as `steps.<id>.exit_code`. A step targets every
    agent with the SAME Job, so per-agent JobResults can disagree; rather
    than invent a fleet-aggregation policy nothing else in the codebase has
    a convention for, this exposes the code only when every agent agrees,
    and None otherwise — a condition author comparing exit_code is almost
    always really asking "did it succeed everywhere," which `steps.<id>.
    status` already answers unambiguously."""
    from lokilinux.models.job import JobResult
    rows = (await db.execute(select(JobResult.exit_code).where(JobResult.job_id == job_id))).scalars().all()
    codes = {c for c in rows if c is not None}
    return codes.pop() if len(codes) == 1 else None


async def _build_condition_context(
    db: AsyncSession, graph: CompiledGraph, step_runs: dict[str, WorkflowStepRun], run: WorkflowRun,
) -> dict:
    """Context handed to utils/expr.py's evaluate_condition — plan §12's
    documented shape: `steps.<id>.{status,exit_code,duration_seconds}`,
    `vars.<name>`, `targets.count`. Only TERMINAL steps get a real
    status; a step that hasn't run yet reads as status=None rather than
    raising, so an expression can legitimately check `steps.x.status ==
    'SUCCEEDED'` for a step later in the graph without an AttributeError."""
    steps_ctx: dict[str, dict] = {}
    for step_id, sr in step_runs.items():
        duration = None
        if sr.started_at and sr.completed_at:
            duration = (sr.completed_at - sr.started_at).total_seconds()
        exit_code = await _step_exit_code(db, sr.job_id) if sr.job_id is not None else None
        steps_ctx[step_id] = {"status": sr.status, "exit_code": exit_code, "duration_seconds": duration}
    return {
        "steps": steps_ctx,
        "vars": run.vars or {},
        "targets": {"count": len(run.targets.get("agent_ids", []))},
    }


async def _wait_for_agent_satisfied(db: AsyncSession, sr: WorkflowStepRun, step: WorkflowStep, target_agent_ids: list[UUID]) -> tuple[bool, bool]:
    """Polled each tick for a RUNNING wait step. Returns (done, timed_out).
    mode='agent' (default, includes the legacy wait_for_agent alias): no
    heartbeat-count history anywhere in the schema (only Agent.last_heartbeat,
    a single timestamp) — min_heartbeats is therefore read as "how many
    heartbeat intervals must have elapsed since this step started," not an
    exact counted total, and satisfaction also requires last_heartbeat to be
    recent (within one interval of now) so a long-dead agent whose last real
    heartbeat happens to predate the step by enough intervals can't satisfy
    it. mode='duration': satisfied once `seconds` have elapsed since start,
    no agent involved. mode='condition' is not supported yet — rejected at
    the call site so it fails loudly instead of hanging forever."""
    config = step.config or {}
    now = datetime.now(timezone.utc)
    mode = config.get("mode") or "agent"

    if mode == "duration":
        seconds = int(config.get("seconds") or 0)
        elapsed = (now - sr.started_at).total_seconds() if sr.started_at else 0
        return elapsed >= seconds, False

    timeout_seconds = int(config.get("timeout_seconds") or 1800)
    min_heartbeats = int(config.get("min_heartbeats") or 1)

    if sr.started_at and (now - sr.started_at).total_seconds() > timeout_seconds:
        return False, True

    if not target_agent_ids:
        return True, False

    required_elapsed = min_heartbeats * _HEARTBEAT_INTERVAL_SECONDS
    rows = (await db.execute(select(Agent.id, Agent.last_heartbeat).where(Agent.id.in_(target_agent_ids)))).all()
    for _agent_id, last_heartbeat in rows:
        if last_heartbeat is None:
            return False, False
        if sr.started_at and (last_heartbeat - sr.started_at).total_seconds() < required_elapsed:
            return False, False
        if (now - last_heartbeat).total_seconds() > _HEARTBEAT_INTERVAL_SECONDS * 2:
            return False, False  # stale — not actually heartbeating right now
    return True, False


async def advance_run(
    db: AsyncSession, cache: RedisCache, storage: ObjectStorage, run: WorkflowRun, nats=None
) -> None:
    """One tick of the state machine — see module docstring for when this
    is called. No-op for a run that isn't actively RUNNING (WAITING_APPROVAL
    needs a human, terminal states need nothing). `nats` is optional and
    only reaches `notification` steps (_dispatch_notification) — every
    other step type ignores it."""
    if run.status != "RUNNING":
        return

    version = (await db.execute(
        select(WorkflowVersion).where(WorkflowVersion.id == run.workflow_version_id)
    )).scalar_one_or_none()
    if version is None:
        run.status = "FAILED"
        run.error = "workflow version referenced by this run no longer exists"
        run.completed_at = datetime.now(timezone.utc)
        await db.commit()
        return

    graph = CompiledGraph.model_validate(version.graph)
    steps_by_id = {s.id: s for s in graph.steps}
    # Captured once: JobService.create_job's duplicate-active-job guard
    # rolls back on an IntegrityError race (job_service.py), and a
    # rollback unconditionally expires every object in this session — run
    # included, regardless of this session's expire_on_commit=False (that
    # setting only governs commit). run.id is a plain UUID, safe to reuse
    # after that without re-touching the (possibly expired) ORM instance.
    run_id = run.id
    step_runs = await _load_step_runs(db, run_id)
    target_agent_ids = [UUID(a) for a in run.targets.get("agent_ids", [])]

    # 1) Sync any RUNNING step that's reached a terminal state — either a
    # Job (job_id set) or a wait_for_agent poll (job_id stays None for the
    # whole step; see _wait_for_agent_satisfied).
    for sr in step_runs.values():
        if sr.status != "RUNNING":
            continue
        if sr.job_id is not None:
            job = await db.get(Job, sr.job_id)
            if job is not None and job.status in _TERMINAL_JOB_STATUSES:
                sr.status = "SUCCEEDED" if job.status == _TERMINAL_JOB_SUCCESS else "FAILED"
                sr.completed_at = datetime.now(timezone.utc)
                sr.output = {"job_id": str(job.id), "job_status": job.status.value}
                if sr.status == "FAILED":
                    sr.error = f"Job ended in status {job.status.value}"
        elif steps_by_id.get(sr.step_id) and _normalize_type(steps_by_id[sr.step_id].type) == WorkflowNodeType.WAIT:
            done, timed_out = await _wait_for_agent_satisfied(db, sr, steps_by_id[sr.step_id], target_agent_ids)
            if done:
                sr.status = "SUCCEEDED"
                sr.completed_at = datetime.now(timezone.utc)
            elif timed_out:
                sr.status = "FAILED"
                sr.error = "Timed out waiting for a fresh agent heartbeat"
                sr.completed_at = datetime.now(timezone.utc)

    # 2) Determine which PENDING steps are now ready, and which are SKIPPED
    # (every incoming edge's predecessor is terminal, but none matched).
    approval_blocked = False
    for step in graph.steps:
        sr = step_runs[step.id]
        if sr.status != "PENDING":
            continue

        incoming = _incoming_edges(graph, step.id)
        if not incoming:
            ready, skipped = True, False  # entry point
        else:
            preds_terminal = all(step_runs[e.from_].status in ("SUCCEEDED", "FAILED", "SKIPPED") for e in incoming)
            if not preds_terminal:
                continue
            matched = any(
                e.on == "always"
                or (e.on == "success" and step_runs[e.from_].status == "SUCCEEDED")
                or (e.on == "failure" and step_runs[e.from_].status == "FAILED")
                for e in incoming
            )
            ready, skipped = matched, not matched

        if skipped:
            sr.status = "SKIPPED"
            sr.completed_at = datetime.now(timezone.utc)
            continue
        if not ready:
            continue

        if step.disabled:
            sr.status = "SKIPPED"
            sr.completed_at = datetime.now(timezone.utc)
            continue

        normalized = _normalize_type(step.type)

        if normalized == WorkflowNodeType.START:
            sr.status = "SUCCEEDED"
            sr.completed_at = datetime.now(timezone.utc)
            continue

        if normalized == WorkflowNodeType.END:
            outcome = (step.config or {}).get("outcome") or "success"
            sr.status = "FAILED" if outcome == "failure" else "SUCCEEDED"
            sr.completed_at = datetime.now(timezone.utc)
            continue

        if normalized == WorkflowNodeType.APPROVAL:
            sr.status = "WAITING_APPROVAL"
            approval_blocked = True
            continue

        if normalized == WorkflowNodeType.CONDITION:
            # No Job — evaluated synchronously and immediately terminal, so
            # its own SUCCEEDED/FAILED drives the SAME on:success/on:failure
            # edge-matching every other step type already uses (plan §7's
            # "branching" is this, not a second routing mechanism).
            expression = str((step.config or {}).get("expression") or "")
            try:
                context = await _build_condition_context(db, graph, step_runs, run)
                result = evaluate_condition(expression, context)
                sr.status = "SUCCEEDED" if result else "FAILED"
                sr.output = {"expression": expression, "result": result}
                if not result:
                    sr.error = "Condition evaluated to false"
            except ExpressionError as exc:
                sr.status = "FAILED"
                sr.error = f"Condition expression error: {exc}"
            sr.completed_at = datetime.now(timezone.utc)
            continue

        if normalized == WorkflowNodeType.WAIT:
            mode = (step.config or {}).get("mode") or "agent"
            if mode == "condition":
                sr.status = "FAILED"
                sr.error = "wait mode 'condition' is not supported yet"
                sr.completed_at = datetime.now(timezone.utc)
                continue
            # No Job — polled each tick via section 1 above
            # (_wait_for_agent_satisfied) until it succeeds or times out.
            sr.status = "RUNNING"
            sr.started_at = datetime.now(timezone.utc)
            continue

        if normalized == WorkflowNodeType.NOTIFICATION:
            try:
                await _dispatch_notification(db, nats, step, run)
                sr.status = "SUCCEEDED"
            except WorkflowRunError as exc:
                sr.status = "FAILED"
                sr.error = str(exc)
            sr.completed_at = datetime.now(timezone.utc)
            continue

        if normalized == WorkflowNodeType.WEBHOOK:
            try:
                await _dispatch_webhook(step)
                sr.status = "SUCCEEDED"
            except WorkflowRunError as exc:
                sr.status = "FAILED"
                sr.error = str(exc)
            sr.completed_at = datetime.now(timezone.utc)
            continue

        if normalized in _NOT_YET_EXECUTABLE:
            sr.status = "FAILED"
            sr.error = f"step type '{step.type.value}' is not executable yet"
            sr.completed_at = datetime.now(timezone.utc)
            continue

        try:
            job = await _dispatch_step(db, cache, storage, step, target_agent_ids, run.id)
        except (WorkflowRunError, ValueError) as exc:
            # A ValueError here can only be JobService.create_job's
            # duplicate-active-job guard, which rolls back on the
            # IntegrityError race — see run_id's comment above. Reload
            # before touching `sr` (and before any later step this tick,
            # e.g. a CONDITION step reading sibling statuses, or the
            # terminal check below) trips the same expired-attribute
            # MissingGreenlet on one of this run's other step_runs.
            step_runs = await _load_step_runs(db, run_id)
            sr = step_runs[step.id]
            sr.status = "FAILED"
            sr.error = str(exc)
            sr.completed_at = datetime.now(timezone.utc)
            continue

        sr.job_id = job.id
        sr.status = "RUNNING"
        sr.started_at = datetime.now(timezone.utc)

    await db.flush()

    if approval_blocked:
        run.status = "WAITING_APPROVAL"
        await db.commit()
        return

    # 3) Run-level terminal check — nothing left pending or running.
    still_active = any(sr.status in ("PENDING", "RUNNING", "WAITING_APPROVAL") for sr in step_runs.values())
    if not still_active:
        any_failed = any(sr.status == "FAILED" for sr in step_runs.values())
        run.status = "FAILED" if any_failed else "SUCCEEDED"
        run.completed_at = datetime.now(timezone.utc)

    await db.commit()


async def approve_step(
    db: AsyncSession, cache: RedisCache, storage: ObjectStorage, run_id: UUID, step_id: str, *,
    actor: UUID | None, nats=None,
) -> WorkflowRun:
    run = await _get_run(db, run_id)
    step_runs = await _load_step_runs(db, run.id)
    sr = step_runs.get(step_id)
    if sr is None:
        raise HTTPException(status_code=404, detail=f"Step '{step_id}' not found in this run")
    if sr.status != "WAITING_APPROVAL":
        raise HTTPException(status_code=409, detail=f"Step '{step_id}' is not waiting for approval (status: {sr.status})")
    if actor is not None and run.triggered_by is not None and actor == run.triggered_by:
        raise HTTPException(status_code=403, detail="You cannot approve a run you triggered yourself")

    sr.status = "SUCCEEDED"
    sr.completed_at = datetime.now(timezone.utc)
    run.status = "RUNNING"
    await db.commit()

    await AuditService(db).log(
        action="workflow.step_approved", user_id=str(actor) if actor else None,
        resource_type="workflow_run", resource_id=str(run.id), changes={"step_id": step_id},
    )
    await advance_run(db, cache, storage, run, nats)
    return run


async def reject_step(db: AsyncSession, run_id: UUID, step_id: str, *, actor: UUID | None) -> WorkflowRun:
    """A rejected approval fails the run outright — Phase 6 has no rollback
    branch semantics yet (Phase 7's on_failure: branch handles that); every
    other PENDING/WAITING_APPROVAL step is marked SKIPPED, not left dangling."""
    run = await _get_run(db, run_id)
    step_runs = await _load_step_runs(db, run.id)
    sr = step_runs.get(step_id)
    if sr is None:
        raise HTTPException(status_code=404, detail=f"Step '{step_id}' not found in this run")
    if sr.status != "WAITING_APPROVAL":
        raise HTTPException(status_code=409, detail=f"Step '{step_id}' is not waiting for approval (status: {sr.status})")

    sr.status = "FAILED"
    sr.error = "Rejected by approver"
    sr.completed_at = datetime.now(timezone.utc)
    for other in step_runs.values():
        if other.step_id != step_id and other.status in ("PENDING", "WAITING_APPROVAL"):
            other.status = "SKIPPED"
            other.completed_at = datetime.now(timezone.utc)

    run.status = "FAILED"
    run.completed_at = datetime.now(timezone.utc)
    await db.commit()

    await AuditService(db).log(
        action="workflow.step_rejected", user_id=str(actor) if actor else None,
        resource_type="workflow_run", resource_id=str(run.id), changes={"step_id": step_id},
    )
    return run


async def cancel_run(db: AsyncSession, run_id: UUID, *, actor: UUID | None) -> WorkflowRun:
    """Cancels every non-terminal step. A step whose Job is still QUEUED/
    SCHEDULED is cancelled outright (same rule as DELETE /jobs/{id} —
    api/v1/routers/jobs.py's _CANCELLABLE); a step whose Job is already
    RUNNING on an agent can't actually be stopped mid-execution (the system
    has no such channel today), so it's left to finish — only the *run's*
    bookkeeping around it is marked CANCELLED so nothing keeps advancing
    past it."""
    run = await _get_run(db, run_id)
    if run.status in ("SUCCEEDED", "FAILED", "CANCELLED"):
        raise HTTPException(status_code=409, detail=f"Run already terminal (status: {run.status})")

    step_runs = await _load_step_runs(db, run.id)
    for sr in step_runs.values():
        if sr.status in ("PENDING", "WAITING_APPROVAL"):
            sr.status = "CANCELLED"
            sr.completed_at = datetime.now(timezone.utc)
        elif sr.status == "RUNNING":
            sr.status = "CANCELLED"
            sr.completed_at = datetime.now(timezone.utc)
            if sr.job_id is not None:
                job = await db.get(Job, sr.job_id)
                if job is not None and job.status in _CANCELLABLE_JOB_STATUSES:
                    job.status = JobStatus.CANCELLED

    run.status = "CANCELLED"
    run.completed_at = datetime.now(timezone.utc)
    await db.commit()

    await AuditService(db).log(
        action="workflow.run_cancelled", user_id=str(actor) if actor else None,
        resource_type="workflow_run", resource_id=str(run.id),
    )
    return run
