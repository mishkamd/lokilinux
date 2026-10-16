"""MIS-29 point 1 and 2 — shell injection via package names and the port check.

Each test fails on the pre-fix code for the reason named in its docstring.
The sentinel file is created under tmp_path; a stub package manager sits first
on PATH so a rendered upgrade command can run without touching a real one.
"""

import logging
import shutil
import socket
import subprocess
import uuid

import pytest
from sqlalchemy import select

from lokilinux.models.agent import Agent, AgentStatus
from lokilinux.models.cve import CVE, AgentVulnerability
from lokilinux.models.remediation import RemediationAction
from lokilinux.models.workflow import WorkflowRun
from lokilinux.schemas.workflow import WorkflowNodeType, WorkflowStep
from lokilinux.services.agent_service import AgentService
from lokilinux.services.workflow_engine import WorkflowRunError, _compile_check


def _path_with_stub_package_managers(tmp_path) -> str:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("dnf", "apt-get", "zypper"):
        stub = bin_dir / name
        stub.write_text("#!/bin/sh\nexit 0\n")
        stub.chmod(0o755)
    return f"{bin_dir}:/usr/bin:/bin"


def _bash(command: str, cwd, path: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [shutil.which("bash"), "-c", command],
        cwd=cwd,
        env={"PATH": path},
        timeout=10,
        capture_output=True,
    )


# ── point 1: CVE remediation command ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_remediation_command_treats_package_name_as_one_literal_argument(
    client, db_session, tmp_path
):
    """remediate_cve formats _UPGRADE_CMD with the raw package name inside
    double quotes, so `$(touch SENTINEL)` runs when the agent runs the command."""
    agent = Agent(
        agent_id=f"mis29-{uuid.uuid4().hex[:8]}",
        status=AgentStatus.ACTIVE,
        hostname="h-mis29",
        os_distro="rocky",
    )
    db_session.add_all([agent, CVE(cve_id="CVE-2026-9100")])
    await db_session.flush()
    db_session.add(
        AgentVulnerability(
            agent_id=agent.id,
            cve_id="CVE-2026-9100",
            package_name="x$(touch SENTINEL)",
            package_version="1.0",
            fix_available=True,
            status="PATCH_AVAILABLE",
        )
    )
    await db_session.commit()

    resp = await client.post("/api/v1/vulnerabilities/CVE-2026-9100/remediate")
    assert resp.status_code == 201

    action = (
        await db_session.execute(
            select(RemediationAction).where(
                RemediationAction.remediation_plan_id == uuid.UUID(resp.json()["id"])
            )
        )
    ).scalar_one()
    _bash(action.rendered_body, tmp_path, _path_with_stub_package_managers(tmp_path))

    assert not (tmp_path / "SENTINEL").exists()


# ── point 1: ingest of agent-reported CVE rows ───────────────────────────────


@pytest.mark.asyncio
async def test_ingest_drops_package_names_with_shell_syntax_and_keeps_valid_rows(
    db_session, fake_cache, caplog
):
    """A package_name with shell syntax must not be stored as an
    AgentVulnerability (nor its CVE upserted); a valid row from the same
    heartbeat still is. The drop is logged with its count."""
    agent = Agent(agent_id="agent-mis29-ingest", status=AgentStatus.ACTIVE, hostname="h-ingest")
    db_session.add(agent)
    await db_session.commit()

    hostile = ["pkg; rm -rf /", "x$(touch SENTINEL)", "`id`", "a b", "a\nb"]
    vulnerabilities = [
        {
            "cve_id": "CVE-2026-9299",
            "package_name": name,
            "installed_version": "1.0",
            "severity": "HIGH",
        }
        for name in hostile
    ] + [
        {
            "cve_id": "CVE-2026-9201",
            "package_name": "openssl",
            "installed_version": "1.0",
            "severity": "HIGH",
        },
        {
            "cve_id": "CVE-2026-9202",
            "package_name": "python3.11-libs",
            "installed_version": "1.0",
            "severity": "HIGH",
        },
    ]

    with caplog.at_level(logging.WARNING):
        await AgentService(db_session, fake_cache).update_heartbeat(
            "agent-mis29-ingest",
            {"vulnerabilities": vulnerabilities},
        )

    rows = (
        (
            await db_session.execute(
                select(AgentVulnerability.package_name).where(
                    AgentVulnerability.agent_id == agent.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert sorted(rows) == ["openssl", "python3.11-libs"]
    assert (
        await db_session.execute(select(CVE).where(CVE.cve_id == "CVE-2026-9299"))
    ).first() is None
    assert any(
        "dropped 5" in r.getMessage() and "invalid package_name" in r.getMessage()
        for r in caplog.records
    )


@pytest.mark.asyncio
async def test_ingest_drops_overlong_package_name_instead_of_failing_the_heartbeat(
    db_session, fake_cache
):
    """Unbounded, a 256-char name overflows AgentVulnerability.package_name
    (String(255)) and the DB error takes the whole heartbeat down with it."""
    db_session.add(Agent(agent_id="agent-mis29-long", status=AgentStatus.ACTIVE, hostname="h-long"))
    await db_session.commit()

    await AgentService(db_session, fake_cache).update_heartbeat(
        "agent-mis29-long",
        {
            "vulnerabilities": [
                {
                    "cve_id": "CVE-2026-9298",
                    "package_name": "a" * 256,
                    "installed_version": "1.0",
                    "severity": "HIGH",
                },
            ]
        },
    )

    assert (await db_session.execute(select(AgentVulnerability))).first() is None


# ── point 2: port check host ─────────────────────────────────────────────────


def _port_step(host: str, port: int = 22) -> WorkflowStep:
    return WorkflowStep(
        id="probe",
        type=WorkflowNodeType.CHECK,
        name="Probe",
        config={"type": "port", "host": host, "port": port},
    )


def test_port_check_refuses_a_host_that_is_not_a_hostname_or_ip(tmp_path):
    """The port check put host into `bash -c '</dev/tcp/HOST/PORT'`, so
    `x; touch SENTINEL #` ran touch. Such a host must be refused at compile time."""
    sentinel = tmp_path / "SENTINEL"
    with pytest.raises(WorkflowRunError):
        _compile_check(_port_step(f"x; touch {sentinel} #"))
    assert not sentinel.exists()


def test_port_check_still_probes_the_configured_host_and_port(tmp_path):
    """Regression guard for the positional-argument form: the probe must still
    succeed on an open port and fail on a closed one."""
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        open_port = listener.getsockname()[1]
        with socket.socket() as closed:
            closed.bind(("127.0.0.1", 0))
            closed_port = closed.getsockname()[1]

        open_cmd = _compile_check(_port_step("127.0.0.1", open_port))
        closed_cmd = _compile_check(_port_step("127.0.0.1", closed_port))
        open_rc = _bash(open_cmd, tmp_path, "/usr/bin:/bin").returncode
        closed_rc = _bash(closed_cmd, tmp_path, "/usr/bin:/bin").returncode

    assert open_rc == 0
    assert closed_rc != 0


# ── point 1(c): workflow package step name ───────────────────────────────────

PACKAGE_REMOVE_YAML = """
apiVersion: lokilinux/v1
kind: Workflow
metadata:
  name: mis29-package-remove
spec:
  targets: { all: true }
  steps:
    - id: drop
      type: package
      name: Drop
      config: { action: remove, packages: ["pkg; rm -rf /"] }
  edges: []
"""


@pytest.mark.asyncio
async def test_workflow_run_with_hostile_package_name_is_422_and_creates_no_run(client, db_session):
    db_session.add(Agent(agent_id="agent-mis29-wf", status=AgentStatus.ACTIVE, hostname="h-wf"))
    await db_session.commit()
    created = await client.post(
        "/api/v1/workflows", json={"name": "mis29 package", "yaml": PACKAGE_REMOVE_YAML}
    )
    assert created.status_code == 201
    workflow_id = created.json()["id"]
    versions = (await client.get(f"/api/v1/workflows/{workflow_id}/versions")).json()["items"]
    version_id = versions[0]["id"]
    published = await client.post(f"/api/v1/workflows/{workflow_id}/versions/{version_id}/publish")
    assert published.status_code == 422
    assert "invalid package name" in published.json()["detail"]

    resp = await client.post(f"/api/v1/workflows/{workflow_id}/run")

    assert resp.status_code == 409  # never published, so no run can start
    runs = (
        await db_session.execute(
            select(WorkflowRun).where(WorkflowRun.workflow_id == uuid.UUID(workflow_id))
        )
    ).all()
    assert runs == []
