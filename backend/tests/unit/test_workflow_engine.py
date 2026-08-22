"""
Unit tests for the Workflow Engine (services/workflow_engine.py) — the
Phase 6 vertical slice: a linear workflow of command/approval steps must
run end to end against real Agent/Job rows, with approval actually
blocking and unblocking advancement.

No real agent reports back in this test environment, so a step's Job is
"completed" by directly flipping Job.status — exactly what
AgentService._apply_job_results would do on a real heartbeat
(services/agent_service.py:350-378). The engine only reads Job.status; it
does not care how that status was reached.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from lokilinux.models.agent import Agent, AgentStatus
from lokilinux.models.alert import Alert
from lokilinux.models.job import Job, JobStatus
from lokilinux.models.workflow import WorkflowStepRun, WorkflowVersion
from lokilinux.schemas.workflow import WorkflowNodeType, WorkflowStep
from lokilinux.services.workflow_engine import (
    _compile_check,
    _compile_file,
    _compile_package_remove,
    _compile_service,
    _compile_system,
    advance_run,
    approve_step,
    cancel_run,
    reject_step,
    start_run,
)
from lokilinux.services.workflow_service import WorkflowService

LINEAR_TWO_STEP = """
apiVersion: lokilinux/v1
kind: Workflow
metadata:
  name: engine-linear-two-step
spec:
  targets: { all: true }
  steps:
    - { id: precheck, type: command, name: Preflight, config: { command: "true" } }
    - { id: apply, type: command, name: Apply, config: { command: "true" } }
  edges:
    - { from: precheck, to: apply, on: success }
"""

WITH_APPROVAL = """
apiVersion: lokilinux/v1
kind: Workflow
metadata:
  name: engine-with-approval
spec:
  targets: { all: true }
  steps:
    - { id: precheck, type: command, name: Preflight, config: { command: "true" } }
    - { id: gate, type: approval, name: Approve, config: {} }
    - { id: apply, type: command, name: Apply, config: { command: "true" } }
  edges:
    - { from: precheck, to: gate, on: success }
    - { from: gate, to: apply, on: success }
"""


async def _make_agent(db_session) -> Agent:
    agent = Agent(agent_id=f"test-agent-{uuid.uuid4().hex[:8]}", status=AgentStatus.ACTIVE, hostname=f"h-{uuid.uuid4().hex[:6]}")
    db_session.add(agent)
    await db_session.flush()
    return agent


async def _publish(db_session, yaml_source: str, name: str = "Test WF"):
    svc = WorkflowService(db_session)
    workflow = await svc.create_workflow(name=name, yaml_source=yaml_source, created_by=None)
    version_row = (await db_session.execute(
        select(WorkflowVersion).where(WorkflowVersion.workflow_id == workflow.id)
    )).scalar_one()
    published = await svc.publish_version(workflow.id, version_row.id, actor=None)
    return workflow, published


async def _complete_running_step_jobs(db_session, run_id, *, succeed: bool = True):
    step_runs = (await db_session.execute(
        select(WorkflowStepRun).where(WorkflowStepRun.run_id == run_id, WorkflowStepRun.status == "RUNNING")
    )).scalars().all()
    for sr in step_runs:
        job = await db_session.get(Job, sr.job_id)
        job.status = JobStatus.COMPLETED if succeed else JobStatus.FAILED
    await db_session.commit()


@pytest.mark.asyncio
async def test_start_run_requires_published_version(db_session, fake_cache):
    svc = WorkflowService(db_session)
    workflow = await svc.create_workflow(name="Unpublished", yaml_source=LINEAR_TWO_STEP.replace("engine-linear-two-step", "unpublished-wf"), created_by=None)

    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        await start_run(db_session, fake_cache, workflow.id, trigger_type="MANUAL", triggered_by=None)
    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_start_run_with_no_matching_agents_is_422(db_session, fake_cache):
    workflow, _version = await _publish(db_session, LINEAR_TWO_STEP.replace("engine-linear-two-step", "no-agents-wf"))

    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        await start_run(db_session, fake_cache, workflow.id, trigger_type="MANUAL", triggered_by=None)
    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_linear_two_step_run_completes_end_to_end(db_session, fake_cache):
    await _make_agent(db_session)
    workflow, _version = await _publish(db_session, LINEAR_TWO_STEP.replace("engine-linear-two-step", "linear-e2e-wf"))

    run = await start_run(db_session, fake_cache, workflow.id, trigger_type="MANUAL", triggered_by=None)
    assert run.status == "RUNNING"

    step_runs = {sr.step_id: sr for sr in (await db_session.execute(
        select(WorkflowStepRun).where(WorkflowStepRun.run_id == run.id)
    )).scalars().all()}
    assert step_runs["precheck"].status == "RUNNING"
    assert step_runs["precheck"].job_id is not None
    assert step_runs["apply"].status == "PENDING"  # not started — waiting on precheck

    await _complete_running_step_jobs(db_session, run.id, succeed=True)
    await advance_run(db_session, fake_cache, run)

    step_runs = {sr.step_id: sr for sr in (await db_session.execute(
        select(WorkflowStepRun).where(WorkflowStepRun.run_id == run.id)
    )).scalars().all()}
    assert step_runs["precheck"].status == "SUCCEEDED"
    assert step_runs["apply"].status == "RUNNING"
    assert run.status == "RUNNING"

    await _complete_running_step_jobs(db_session, run.id, succeed=True)
    await advance_run(db_session, fake_cache, run)

    assert run.status == "SUCCEEDED"
    assert run.completed_at is not None


@pytest.mark.asyncio
async def test_failed_step_fails_the_run(db_session, fake_cache):
    await _make_agent(db_session)
    workflow, _version = await _publish(db_session, LINEAR_TWO_STEP.replace("engine-linear-two-step", "failing-wf"))

    run = await start_run(db_session, fake_cache, workflow.id, trigger_type="MANUAL", triggered_by=None)
    await _complete_running_step_jobs(db_session, run.id, succeed=False)
    await advance_run(db_session, fake_cache, run)

    step_runs = {sr.step_id: sr for sr in (await db_session.execute(
        select(WorkflowStepRun).where(WorkflowStepRun.run_id == run.id)
    )).scalars().all()}
    assert step_runs["precheck"].status == "FAILED"
    # No edge matched on: success from a FAILED predecessor -> apply is SKIPPED, not left PENDING forever.
    assert step_runs["apply"].status == "SKIPPED"
    assert run.status == "FAILED"


@pytest.mark.asyncio
async def test_approval_blocks_then_unblocks_the_run(db_session, fake_cache):
    await _make_agent(db_session)
    workflow, _version = await _publish(db_session, WITH_APPROVAL.replace("engine-with-approval", "approval-wf"))

    run = await start_run(db_session, fake_cache, workflow.id, trigger_type="MANUAL", triggered_by=None)
    await _complete_running_step_jobs(db_session, run.id, succeed=True)
    await advance_run(db_session, fake_cache, run)

    assert run.status == "WAITING_APPROVAL"
    step_runs = {sr.step_id: sr for sr in (await db_session.execute(
        select(WorkflowStepRun).where(WorkflowStepRun.run_id == run.id)
    )).scalars().all()}
    assert step_runs["gate"].status == "WAITING_APPROVAL"
    assert step_runs["apply"].status == "PENDING"

    await approve_step(db_session, fake_cache, run.id, "gate", actor=None)

    step_runs = {sr.step_id: sr for sr in (await db_session.execute(
        select(WorkflowStepRun).where(WorkflowStepRun.run_id == run.id)
    )).scalars().all()}
    assert step_runs["gate"].status == "SUCCEEDED"
    assert step_runs["apply"].status == "RUNNING"  # approval unblocked it and advance_run ran immediately
    assert run.status == "RUNNING"

    await _complete_running_step_jobs(db_session, run.id, succeed=True)
    await advance_run(db_session, fake_cache, run)
    assert run.status == "SUCCEEDED"


@pytest.mark.asyncio
async def test_approver_cannot_be_the_run_trigger(db_session, fake_cache):
    """Faza 11 — no-self-approval, the pattern already established for
    baseline DRAFT submissions (docs/compliance/06-BASELINE.md): whoever
    started the run cannot be the one clearing its approval gate."""
    await _make_agent(db_session)
    workflow, _version = await _publish(db_session, WITH_APPROVAL.replace("engine-with-approval", "self-approve-wf"))
    triggerer = uuid.uuid4()

    run = await start_run(db_session, fake_cache, workflow.id, trigger_type="MANUAL", triggered_by=triggerer)
    await _complete_running_step_jobs(db_session, run.id, succeed=True)
    await advance_run(db_session, fake_cache, run)
    assert run.status == "WAITING_APPROVAL"

    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        await approve_step(db_session, fake_cache, run.id, "gate", actor=triggerer)
    assert exc_info.value.status_code == 403

    step_runs = {sr.step_id: sr for sr in (await db_session.execute(
        select(WorkflowStepRun).where(WorkflowStepRun.run_id == run.id)
    )).scalars().all()}
    assert step_runs["gate"].status == "WAITING_APPROVAL"  # rejected attempt did not change anything


@pytest.mark.asyncio
async def test_a_different_actor_can_approve(db_session, fake_cache):
    await _make_agent(db_session)
    workflow, _version = await _publish(db_session, WITH_APPROVAL.replace("engine-with-approval", "other-approve-wf"))
    triggerer, approver = uuid.uuid4(), uuid.uuid4()

    run = await start_run(db_session, fake_cache, workflow.id, trigger_type="MANUAL", triggered_by=triggerer)
    await _complete_running_step_jobs(db_session, run.id, succeed=True)
    await advance_run(db_session, fake_cache, run)

    await approve_step(db_session, fake_cache, run.id, "gate", actor=approver)

    step_runs = {sr.step_id: sr for sr in (await db_session.execute(
        select(WorkflowStepRun).where(WorkflowStepRun.run_id == run.id)
    )).scalars().all()}
    assert step_runs["gate"].status == "SUCCEEDED"


@pytest.mark.asyncio
async def test_rejecting_approval_fails_the_run_and_skips_the_rest(db_session, fake_cache):
    await _make_agent(db_session)
    workflow, _version = await _publish(db_session, WITH_APPROVAL.replace("engine-with-approval", "reject-wf"))

    run = await start_run(db_session, fake_cache, workflow.id, trigger_type="MANUAL", triggered_by=None)
    await _complete_running_step_jobs(db_session, run.id, succeed=True)
    await advance_run(db_session, fake_cache, run)
    assert run.status == "WAITING_APPROVAL"

    await reject_step(db_session, run.id, "gate", actor=None)

    step_runs = {sr.step_id: sr for sr in (await db_session.execute(
        select(WorkflowStepRun).where(WorkflowStepRun.run_id == run.id)
    )).scalars().all()}
    assert step_runs["gate"].status == "FAILED"
    assert step_runs["apply"].status == "SKIPPED"
    assert run.status == "FAILED"


@pytest.mark.asyncio
async def test_cancel_run_marks_pending_and_running_steps_cancelled(db_session, fake_cache):
    await _make_agent(db_session)
    workflow, _version = await _publish(db_session, LINEAR_TWO_STEP.replace("engine-linear-two-step", "cancel-wf"))

    run = await start_run(db_session, fake_cache, workflow.id, trigger_type="MANUAL", triggered_by=None)
    await cancel_run(db_session, run.id, actor=None)

    assert run.status == "CANCELLED"
    step_runs = {sr.step_id: sr for sr in (await db_session.execute(
        select(WorkflowStepRun).where(WorkflowStepRun.run_id == run.id)
    )).scalars().all()}
    assert step_runs["precheck"].status == "CANCELLED"
    assert step_runs["apply"].status == "CANCELLED"


@pytest.mark.asyncio
async def test_dry_run_creates_no_jobs(db_session, fake_cache):
    await _make_agent(db_session)
    workflow, _version = await _publish(db_session, LINEAR_TWO_STEP.replace("engine-linear-two-step", "dry-run-wf"))

    run = await start_run(db_session, fake_cache, workflow.id, trigger_type="MANUAL", triggered_by=None, is_dry_run=True)

    step_runs = (await db_session.execute(
        select(WorkflowStepRun).where(WorkflowStepRun.run_id == run.id)
    )).scalars().all()
    assert all(sr.status == "PENDING" for sr in step_runs)
    assert all(sr.job_id is None for sr in step_runs)


# ── Phase 7: condition steps ────────────────────────────────────────────

WITH_CONDITION_ROLLBACK = """
apiVersion: lokilinux/v1
kind: Workflow
metadata:
  name: engine-condition-rollback
spec:
  targets: { all: true }
  steps:
    - { id: upgrade, type: command, name: Upgrade, config: { command: "true" } }
    - { id: check, type: condition, name: Check, config: { expression: "steps.upgrade.status == 'SUCCEEDED'" } }
    - { id: finish, type: command, name: Finish, config: { command: "true" } }
    - { id: rollback, type: command, name: Rollback, config: { command: "true" } }
  edges:
    - { from: upgrade, to: check, on: always }
    - { from: check, to: finish, on: success }
    - { from: check, to: rollback, on: failure }
"""


@pytest.mark.asyncio
async def test_condition_true_takes_the_success_edge(db_session, fake_cache):
    await _make_agent(db_session)
    workflow, _version = await _publish(db_session, WITH_CONDITION_ROLLBACK.replace("engine-condition-rollback", "cond-true-wf"))

    run = await start_run(db_session, fake_cache, workflow.id, trigger_type="MANUAL", triggered_by=None)
    await _complete_running_step_jobs(db_session, run.id, succeed=True)
    await advance_run(db_session, fake_cache, run)  # dispatches `check` (no Job — synchronous)
    await advance_run(db_session, fake_cache, run)  # advances past check to finish

    step_runs = {sr.step_id: sr for sr in (await db_session.execute(
        select(WorkflowStepRun).where(WorkflowStepRun.run_id == run.id)
    )).scalars().all()}
    assert step_runs["check"].status == "SUCCEEDED"
    assert step_runs["check"].job_id is None  # no Job — evaluated synchronously
    assert step_runs["finish"].status == "RUNNING"
    assert step_runs["rollback"].status == "SKIPPED"


@pytest.mark.asyncio
async def test_condition_false_takes_the_failure_edge_rollback_branch(db_session, fake_cache):
    await _make_agent(db_session)
    workflow, _version = await _publish(db_session, WITH_CONDITION_ROLLBACK.replace("engine-condition-rollback", "cond-false-wf"))

    run = await start_run(db_session, fake_cache, workflow.id, trigger_type="MANUAL", triggered_by=None)
    await _complete_running_step_jobs(db_session, run.id, succeed=False)  # upgrade fails
    await advance_run(db_session, fake_cache, run)
    await advance_run(db_session, fake_cache, run)

    step_runs = {sr.step_id: sr for sr in (await db_session.execute(
        select(WorkflowStepRun).where(WorkflowStepRun.run_id == run.id)
    )).scalars().all()}
    assert step_runs["check"].status == "FAILED"  # expression was false
    assert step_runs["finish"].status == "SKIPPED"
    assert step_runs["rollback"].status == "RUNNING"


@pytest.mark.asyncio
async def test_condition_referencing_unknown_step_fails_the_step_not_the_process(db_session, fake_cache):
    await _make_agent(db_session)
    bad = WITH_CONDITION_ROLLBACK.replace("engine-condition-rollback", "cond-bad-wf").replace(
        "steps.upgrade.status == 'SUCCEEDED'", "steps.nonexistent.status == 'SUCCEEDED'",
    )
    workflow, _version = await _publish(db_session, bad)

    run = await start_run(db_session, fake_cache, workflow.id, trigger_type="MANUAL", triggered_by=None)
    await _complete_running_step_jobs(db_session, run.id, succeed=True)
    await advance_run(db_session, fake_cache, run)

    step_runs = {sr.step_id: sr for sr in (await db_session.execute(
        select(WorkflowStepRun).where(WorkflowStepRun.run_id == run.id)
    )).scalars().all()}
    assert step_runs["check"].status == "FAILED"
    assert "Condition expression error" in step_runs["check"].error


# ── Phase 7: wait_for_agent steps ───────────────────────────────────────

WITH_WAIT_FOR_AGENT = """
apiVersion: lokilinux/v1
kind: Workflow
metadata:
  name: engine-wait-for-agent
spec:
  targets: { all: true }
  steps:
    - { id: reboot, type: command, name: Reboot, config: { command: "true" } }
    - { id: wait, type: wait_for_agent, name: Wait, config: { timeout_seconds: 300, min_heartbeats: 1 } }
    - { id: verify, type: command, name: Verify, config: { command: "true" } }
  edges:
    - { from: reboot, to: wait, on: success }
    - { from: wait, to: verify, on: success }
"""


@pytest.mark.asyncio
async def test_wait_for_agent_goes_running_with_no_job(db_session, fake_cache):
    await _make_agent(db_session)
    workflow, _version = await _publish(db_session, WITH_WAIT_FOR_AGENT.replace("engine-wait-for-agent", "wfa-running-wf"))

    run = await start_run(db_session, fake_cache, workflow.id, trigger_type="MANUAL", triggered_by=None)
    await _complete_running_step_jobs(db_session, run.id, succeed=True)
    await advance_run(db_session, fake_cache, run)

    step_runs = {sr.step_id: sr for sr in (await db_session.execute(
        select(WorkflowStepRun).where(WorkflowStepRun.run_id == run.id)
    )).scalars().all()}
    assert step_runs["wait"].status == "RUNNING"
    assert step_runs["wait"].job_id is None
    assert step_runs["wait"].started_at is not None


@pytest.mark.asyncio
async def test_wait_for_agent_succeeds_once_enough_heartbeat_time_has_passed(db_session, fake_cache):
    agent = await _make_agent(db_session)
    workflow, _version = await _publish(db_session, WITH_WAIT_FOR_AGENT.replace("engine-wait-for-agent", "wfa-succeed-wf"))

    run = await start_run(db_session, fake_cache, workflow.id, trigger_type="MANUAL", triggered_by=None)
    await _complete_running_step_jobs(db_session, run.id, succeed=True)
    await advance_run(db_session, fake_cache, run)  # `wait` goes RUNNING

    # Backdate the step's start so min_heartbeats*60s has already "elapsed",
    # and give the agent a fresh heartbeat — matches what a real reboot ->
    # reconnect cycle looks like without waiting 60 real seconds in a test.
    step_runs = {sr.step_id: sr for sr in (await db_session.execute(
        select(WorkflowStepRun).where(WorkflowStepRun.run_id == run.id)
    )).scalars().all()}
    step_runs["wait"].started_at = datetime.now(timezone.utc) - timedelta(seconds=120)
    agent.last_heartbeat = datetime.now(timezone.utc)
    await db_session.commit()

    await advance_run(db_session, fake_cache, run)

    step_runs = {sr.step_id: sr for sr in (await db_session.execute(
        select(WorkflowStepRun).where(WorkflowStepRun.run_id == run.id)
    )).scalars().all()}
    assert step_runs["wait"].status == "SUCCEEDED"
    assert step_runs["verify"].status == "RUNNING"


@pytest.mark.asyncio
async def test_wait_for_agent_times_out(db_session, fake_cache):
    agent = await _make_agent(db_session)
    yaml_source = WITH_WAIT_FOR_AGENT.replace("engine-wait-for-agent", "wfa-timeout-wf").replace("timeout_seconds: 300", "timeout_seconds: 60")
    workflow, _version = await _publish(db_session, yaml_source)

    run = await start_run(db_session, fake_cache, workflow.id, trigger_type="MANUAL", triggered_by=None)
    await _complete_running_step_jobs(db_session, run.id, succeed=True)
    await advance_run(db_session, fake_cache, run)  # `wait` goes RUNNING (timeout_seconds: 60)

    step_runs = {sr.step_id: sr for sr in (await db_session.execute(
        select(WorkflowStepRun).where(WorkflowStepRun.run_id == run.id)
    )).scalars().all()}
    step_runs["wait"].started_at = datetime.now(timezone.utc) - timedelta(seconds=120)
    agent.last_heartbeat = None  # agent never came back
    await db_session.commit()

    await advance_run(db_session, fake_cache, run)

    step_runs = {sr.step_id: sr for sr in (await db_session.execute(
        select(WorkflowStepRun).where(WorkflowStepRun.run_id == run.id)
    )).scalars().all()}
    assert step_runs["wait"].status == "FAILED"
    assert "Timed out" in step_runs["wait"].error
    assert step_runs["verify"].status == "SKIPPED"
    assert run.status == "FAILED"


# ── Partea III: compile-down ────────────────────────────────────────────
# Pure functions — no DB needed. Assert both the generated command AND
# that shell metacharacters in config values get safely quoted (plan §3's
# "Cerință de securitate, nu opțională").

_INJECTION = "nginx; rm -rf /"


def _step(step_type: WorkflowNodeType, config: dict, step_id: str = "s") -> WorkflowStep:
    return WorkflowStep(id=step_id, type=step_type, name="Test", config=config)


def test_compile_service_generates_systemctl_command():
    cmd = _compile_service(_step(WorkflowNodeType.SERVICE, {"action": "restart", "name": "nginx"}))
    assert cmd == "systemctl restart nginx"


def test_compile_service_quotes_injection_attempt():
    cmd = _compile_service(_step(WorkflowNodeType.SERVICE, {"action": "restart", "name": _INJECTION}))
    assert cmd == "systemctl restart 'nginx; rm -rf /'"
    assert "; rm -rf /" not in cmd.split("'", 1)[0]  # not outside the quoted argument


def test_compile_service_rejects_unknown_action():
    with pytest.raises(Exception):
        _compile_service(_step(WorkflowNodeType.SERVICE, {"action": "delete", "name": "nginx"}))


def test_compile_system_reboot_uses_deferred_execution():
    cmd = _compile_system(_step(WorkflowNodeType.SYSTEM, {"action": "reboot", "delay_seconds": 5}))
    assert cmd == "systemd-run --on-active=5s systemctl reboot"


def test_compile_system_hostname_quotes_value():
    cmd = _compile_system(_step(WorkflowNodeType.SYSTEM, {"action": "hostname", "value": _INJECTION}))
    assert cmd == "hostnamectl set-hostname 'nginx; rm -rf /'"


def test_compile_file_create_writes_content_and_quotes_it():
    cmd = _compile_file(_step(WorkflowNodeType.FILE, {"action": "create", "path": "/etc/motd", "content": _INJECTION}))
    assert "rm -rf /" not in cmd.replace("'nginx; rm -rf /'", "")
    assert cmd.startswith("printf '%s' 'nginx; rm -rf /' > /etc/motd")


def test_compile_file_chown_quotes_owner_group():
    cmd = _compile_file(_step(WorkflowNodeType.FILE, {"action": "chown", "path": "/tmp/x", "owner": "root", "group": _INJECTION}))
    assert cmd == "chown 'root:nginx; rm -rf /' /tmp/x"


def test_compile_package_remove_or_chains_and_quotes_names():
    cmd = _compile_package_remove(_step(WorkflowNodeType.PACKAGE, {"action": "remove", "packages": ["nginx", _INJECTION]}))
    assert "dnf remove -y nginx 'nginx; rm -rf /'" in cmd
    assert "apt-get remove -y nginx 'nginx; rm -rf /'" in cmd


def test_compile_check_command_type_honors_expect_exit_code():
    """The dead-field bug (F-plan §2): expect_exit_code was declared in the
    UI, written to YAML, and read nowhere in the backend. Now it must
    actually gate pass/fail."""
    cmd = _compile_check(_step(WorkflowNodeType.CHECK, {"type": "command", "command": "true", "expect_exit_code": 0}))
    assert cmd == "true; test $? -eq 0"


def test_compile_check_service_type_quotes_service_name():
    cmd = _compile_check(_step(WorkflowNodeType.CHECK, {"type": "service", "service": _INJECTION}))
    assert cmd == "systemctl is-active 'nginx; rm -rf /'"


def test_compile_check_port_type_generates_dev_tcp_probe():
    cmd = _compile_check(_step(WorkflowNodeType.CHECK, {"type": "port", "host": "localhost", "port": 443}))
    assert cmd == "timeout 2 bash -c '</dev/tcp/localhost/443'"


def test_compile_check_disk_type_generates_df_comparison():
    cmd = _compile_check(_step(WorkflowNodeType.CHECK, {"type": "disk", "path": "/", "min_free_gb": 5}))
    assert "df --output=avail -BG /" in cmd
    assert "-ge 5" in cmd


def test_compile_check_legacy_validation_alias_defaults_to_command_type():
    """The exact flat {command, expect_exit_code} shape the old `validation`
    node used, with no `type` key at all — must resolve to the 'command'
    variant, not raise."""
    cmd = _compile_check(_step(WorkflowNodeType.VALIDATION, {"command": "systemctl is-system-running --quiet || true", "expect_exit_code": 0}))
    assert cmd == "systemctl is-system-running --quiet || true; test $? -eq 0"


def test_compile_check_unsupported_type_raises():
    with pytest.raises(Exception):
        _compile_check(_step(WorkflowNodeType.CHECK, {"type": "certificate"}))


WITH_SERVICE_STEP = """
apiVersion: lokilinux/v1
kind: Workflow
metadata:
  name: engine-service-compile-down
spec:
  targets: { all: true }
  steps:
    - { id: restart_nginx, type: service, name: Restart nginx, config: { action: restart, name: nginx } }
  edges: []
"""


@pytest.mark.asyncio
async def test_service_step_dispatches_as_custom_command_job(db_session, fake_cache):
    """The Compile-Down Rule end to end: a `service` node produces a
    CUSTOM_COMMAND Job with the compiled shell — zero agent changes."""
    await _make_agent(db_session)
    workflow, _version = await _publish(db_session, WITH_SERVICE_STEP.replace("engine-service-compile-down", "service-compile-wf"))

    run = await start_run(db_session, fake_cache, workflow.id, trigger_type="MANUAL", triggered_by=None)

    step_runs = {sr.step_id: sr for sr in (await db_session.execute(
        select(WorkflowStepRun).where(WorkflowStepRun.run_id == run.id)
    )).scalars().all()}
    assert step_runs["restart_nginx"].status == "RUNNING"
    job = await db_session.get(Job, step_runs["restart_nginx"].job_id)
    assert job.job_type == "CUSTOM_COMMAND"
    assert job.parameters["command"] == "systemctl restart nginx"


# ── Faza 10: native dispatch gate ───────────────────────────────────────

@pytest.mark.asyncio
async def test_service_step_dispatches_natively_when_agent_meets_minimum(db_session, fake_cache):
    """Once every target agent's agent_version meets MIN_AGENT_VERSION_NATIVE_MODULES,
    a service step must produce a real SERVICE job (agent/internal/modules/service.go),
    not a compiled shell command."""
    agent = await _make_agent(db_session)
    agent.agent_version = "0.36.0"
    await db_session.commit()
    workflow, _version = await _publish(db_session, WITH_SERVICE_STEP.replace("engine-service-compile-down", "service-native-wf"))

    run = await start_run(db_session, fake_cache, workflow.id, trigger_type="MANUAL", triggered_by=None)

    step_runs = {sr.step_id: sr for sr in (await db_session.execute(
        select(WorkflowStepRun).where(WorkflowStepRun.run_id == run.id)
    )).scalars().all()}
    job = await db_session.get(Job, step_runs["restart_nginx"].job_id)
    assert job.job_type == "SERVICE"
    assert job.parameters["action"] == "restart"
    assert job.parameters["name"] == "nginx"


@pytest.mark.asyncio
async def test_service_step_falls_back_to_compile_down_when_one_target_agent_is_old(db_session, fake_cache):
    """A Job's job_type is uniform across every agent it fans out to — if
    even one of two target agents is below the minimum, the whole Job must
    stay compile-down rather than splitting job_type per agent."""
    new_agent = await _make_agent(db_session)
    new_agent.agent_version = "0.36.0"
    old_agent = await _make_agent(db_session)
    old_agent.agent_version = "0.35.3"
    await db_session.commit()
    workflow, _version = await _publish(db_session, WITH_SERVICE_STEP.replace("engine-service-compile-down", "service-mixed-wf"))

    run = await start_run(db_session, fake_cache, workflow.id, trigger_type="MANUAL", triggered_by=None)

    step_runs = {sr.step_id: sr for sr in (await db_session.execute(
        select(WorkflowStepRun).where(WorkflowStepRun.run_id == run.id)
    )).scalars().all()}
    job = await db_session.get(Job, step_runs["restart_nginx"].job_id)
    assert job.job_type == "CUSTOM_COMMAND"
    assert job.parameters["command"] == "systemctl restart nginx"


WITH_REBOOT_STEP = """
apiVersion: lokilinux/v1
kind: Workflow
metadata:
  name: engine-reboot-native
spec:
  targets: { all: true }
  steps:
    - { id: reboot, type: system, name: Reboot, config: { action: reboot, delay_seconds: 5 } }
  edges: []
"""


@pytest.mark.asyncio
async def test_system_reboot_dispatches_natively_when_agent_meets_minimum(db_session, fake_cache):
    agent = await _make_agent(db_session)
    agent.agent_version = "0.36.0"
    await db_session.commit()
    workflow, _version = await _publish(db_session, WITH_REBOOT_STEP.replace("engine-reboot-native", "reboot-native-wf"))

    run = await start_run(db_session, fake_cache, workflow.id, trigger_type="MANUAL", triggered_by=None)

    step_runs = {sr.step_id: sr for sr in (await db_session.execute(
        select(WorkflowStepRun).where(WorkflowStepRun.run_id == run.id)
    )).scalars().all()}
    job = await db_session.get(Job, step_runs["reboot"].job_id)
    assert job.job_type == "REBOOT"
    assert job.parameters["action"] == "reboot"


WITH_SYSTEM_HOSTNAME_STEP = """
apiVersion: lokilinux/v1
kind: Workflow
metadata:
  name: engine-hostname-native
spec:
  targets: { all: true }
  steps:
    - { id: set_hostname, type: system, name: Set hostname, config: { action: hostname, value: web01 } }
  edges: []
"""


@pytest.mark.asyncio
async def test_system_hostname_always_compiles_to_shell_even_on_a_new_agent(db_session, fake_cache):
    """reboot.go only implements action=reboot|shutdown — hostname/timezone/
    sysctl have no native module regardless of agent version."""
    agent = await _make_agent(db_session)
    agent.agent_version = "0.99.0"
    await db_session.commit()
    workflow, _version = await _publish(db_session, WITH_SYSTEM_HOSTNAME_STEP.replace("engine-hostname-native", "hostname-native-wf"))

    run = await start_run(db_session, fake_cache, workflow.id, trigger_type="MANUAL", triggered_by=None)

    step_runs = {sr.step_id: sr for sr in (await db_session.execute(
        select(WorkflowStepRun).where(WorkflowStepRun.run_id == run.id)
    )).scalars().all()}
    job = await db_session.get(Job, step_runs["set_hostname"].job_id)
    assert job.job_type == "CUSTOM_COMMAND"
    assert job.parameters["command"] == "hostnamectl set-hostname web01"


WITH_FILE_STEP = """
apiVersion: lokilinux/v1
kind: Workflow
metadata:
  name: engine-file-native
spec:
  targets: { all: true }
  steps:
    - { id: write, type: file, name: Write motd, config: { action: create, path: /etc/motd, content: hello } }
  edges: []
"""


@pytest.mark.asyncio
async def test_file_step_dispatches_natively_when_agent_meets_minimum(db_session, fake_cache):
    agent = await _make_agent(db_session)
    agent.agent_version = "0.37.2"
    await db_session.commit()
    workflow, _version = await _publish(db_session, WITH_FILE_STEP.replace("engine-file-native", "file-native-wf"))

    run = await start_run(db_session, fake_cache, workflow.id, trigger_type="MANUAL", triggered_by=None)

    step_runs = {sr.step_id: sr for sr in (await db_session.execute(
        select(WorkflowStepRun).where(WorkflowStepRun.run_id == run.id)
    )).scalars().all()}
    job = await db_session.get(Job, step_runs["write"].job_id)
    assert job.job_type == "FILE"
    assert job.parameters["path"] == "/etc/motd"
    assert job.parameters["content"] == "hello"


# ── Etapa 4: notification / webhook ─────────────────────────────────────

WITH_NOTIFICATION_STEP = """
apiVersion: lokilinux/v1
kind: Workflow
metadata:
  name: engine-notification-compile-down
spec:
  targets: { all: true }
  steps:
    - { id: notify, type: notification, name: Notify, config: { subject: Done, message: All good } }
  edges: []
"""


@pytest.mark.asyncio
async def test_notification_step_creates_an_alert_with_no_job(db_session, fake_cache):
    await _make_agent(db_session)
    workflow, _version = await _publish(db_session, WITH_NOTIFICATION_STEP.replace("engine-notification-compile-down", "notify-wf"))

    run = await start_run(db_session, fake_cache, workflow.id, trigger_type="MANUAL", triggered_by=None)

    step_runs = {sr.step_id: sr for sr in (await db_session.execute(
        select(WorkflowStepRun).where(WorkflowStepRun.run_id == run.id)
    )).scalars().all()}
    assert step_runs["notify"].status == "SUCCEEDED"
    assert step_runs["notify"].job_id is None
    assert run.status == "SUCCEEDED"

    alerts = (await db_session.execute(select(Alert).where(Alert.title == "Done"))).scalars().all()
    assert len(alerts) == 1
    assert alerts[0].description == "All good"


@pytest.mark.asyncio
async def test_second_notification_for_the_same_run_and_step_does_not_duplicate_the_alert(db_session, fake_cache):
    """AlertService's ACTIVE-alert dedup is scoped by (agent_id, alert_type)
    — _dispatch_notification derives alert_type from run_id+step_id so a
    re-tick of the SAME step run can't spam duplicate alerts, without
    accidentally deduping two different runs' notifications against
    each other (plan §Etapa4)."""
    await _make_agent(db_session)
    workflow, _version = await _publish(db_session, WITH_NOTIFICATION_STEP.replace("engine-notification-compile-down", "notify-dedup-wf"))

    run = await start_run(db_session, fake_cache, workflow.id, trigger_type="MANUAL", triggered_by=None)
    await advance_run(db_session, fake_cache, run)  # already-SUCCEEDED step is a no-op re-tick

    alerts = (await db_session.execute(select(Alert).where(Alert.title == "Done"))).scalars().all()
    assert len(alerts) == 1


WITH_WEBHOOK_STEP = """
apiVersion: lokilinux/v1
kind: Workflow
metadata:
  name: engine-webhook-compile-down
spec:
  targets: { all: true }
  steps:
    - { id: hook, type: webhook, name: Hook, config: { url: "http://127.0.0.1:1/unreachable" } }
  edges: []
"""


@pytest.mark.asyncio
async def test_webhook_step_fails_cleanly_on_unreachable_url(db_session, fake_cache):
    """No mock HTTP server in this test environment — asserting against a
    connection failure is still a real, meaningful check: the step must
    fail the run rather than silently reporting success for a request that
    was never delivered."""
    await _make_agent(db_session)
    workflow, _version = await _publish(db_session, WITH_WEBHOOK_STEP.replace("engine-webhook-compile-down", "webhook-wf"))

    run = await start_run(db_session, fake_cache, workflow.id, trigger_type="MANUAL", triggered_by=None)

    step_runs = {sr.step_id: sr for sr in (await db_session.execute(
        select(WorkflowStepRun).where(WorkflowStepRun.run_id == run.id)
    )).scalars().all()}
    assert step_runs["hook"].status == "FAILED"
    assert step_runs["hook"].job_id is None
    assert "request failed" in step_runs["hook"].error
    assert run.status == "FAILED"
