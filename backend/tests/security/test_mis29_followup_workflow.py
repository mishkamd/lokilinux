"""MIS-29 follow-up: workflow no-self-approval for nanoid publishers, publish-time
validation of package names and probe hosts, and the network-check host guard.

Each regression test fails on the pre-fix code for the reason named in its
docstring. The two controls (other_nanoid_user, network valid host) pass before
and after the fix.
"""

import uuid

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import select

from lokilinux.models.agent import Agent, AgentStatus
from lokilinux.models.workflow import Workflow, WorkflowVersion
from lokilinux.schemas.workflow import WorkflowNodeType, WorkflowStep
from lokilinux.services.workflow_engine import WorkflowRunError, _compile_check, start_run
from lokilinux.services.workflow_service import WorkflowService

# Better Auth ids: nanoids, never parseable as UUID.
NANOID_PUBLISHER = "k3Xq9wLbz0nanoidA"
NANOID_OTHER = "Pm4vT8nQz2nanoidB"

GATE_STEP = "{ id: gate, type: approval, name: Approve, config: {} }"
PACKAGE_STEP = (
    '{ id: drop, type: package, name: Drop, '
    'config: { action: install, packages: ["pkg; rm -rf /"] } }'
)
NETWORK_STEP = (
    '{ id: probe, type: check, name: Probe, '
    'config: { type: network, host: "x; touch SENTINEL" } }'
)
PORT_STEP = (
    '{ id: probe, type: check, name: Probe, '
    'config: { type: port, host: "x; touch SENTINEL", port: 22 } }'
)


def _workflow_yaml(slug: str, step: str) -> str:
    return (
        "apiVersion: lokilinux/v1\nkind: Workflow\nmetadata:\n"
        f"  name: {slug}\nspec:\n  targets: {{ all: true }}\n"
        f"  steps:\n    - {step}\n  edges: []\n"
    )


def _make_agent() -> Agent:
    return Agent(
        agent_id=str(uuid.uuid4()),
        status=AgentStatus.ACTIVE,
        hostname=f"host-{uuid.uuid4().hex[:8]}",
    )


async def _create_draft(client: AsyncClient, slug: str, step: str) -> tuple[str, str]:
    created = await client.post(
        "/api/v1/workflows", json={"name": slug, "yaml": _workflow_yaml(slug, step)},
    )
    assert created.status_code == 201, created.text
    workflow_id = created.json()["id"]
    versions = (await client.get(f"/api/v1/workflows/{workflow_id}/versions")).json()["items"]
    return workflow_id, versions[0]["id"]


async def _publish_and_start_gate_run(client, db_session, slug: str) -> tuple[str, str]:
    """Publishes a gate-only workflow as the current user, then starts it. The
    run stops at the approval gate; returns (workflow_id, run_id)."""
    workflow_id, version_id = await _create_draft(client, slug, GATE_STEP)
    published = await client.post(f"/api/v1/workflows/{workflow_id}/versions/{version_id}/publish")
    assert published.status_code == 200, published.text

    db_session.add(_make_agent())
    await db_session.commit()

    run = await client.post(f"/api/v1/workflows/{workflow_id}/run")
    assert run.status_code == 202, run.text
    assert run.json()["status"] == "WAITING_APPROVAL"
    return workflow_id, run.json()["id"]


# ── no-self-approval: nanoid publisher ───────────────────────────────────────


@pytest.mark.asyncio
async def test_nanoid_publisher_cannot_approve_own_run(client, db_session, current_user):
    """Before the fix, approve_step's publisher check only ran for a UUID actor.
    A nanoid publisher has published_by NULL and the route passes actor=None,
    so the gate was cleared (200) instead of refused (403)."""
    current_user["id"] = NANOID_PUBLISHER
    _workflow_id, run_id = await _publish_and_start_gate_run(client, db_session, "mis29-nanoid-own")

    resp = await client.post(f"/api/v1/workflows/runs/{run_id}/steps/gate/approve")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_other_nanoid_user_can_approve_the_run(client, db_session, current_user):
    """Control: the nanoid guard must refuse only the publisher, not every nanoid user."""
    current_user["id"] = NANOID_PUBLISHER
    _workflow_id, run_id = await _publish_and_start_gate_run(client, db_session, "mis29-peer")

    current_user["id"] = NANOID_OTHER
    resp = await client.post(f"/api/v1/workflows/runs/{run_id}/steps/gate/approve")
    assert resp.status_code == 200
    assert resp.json()["status"] == "SUCCEEDED"


@pytest.mark.asyncio
async def test_nanoid_user_cannot_approve_a_run_they_triggered(client, db_session, current_user):
    """A nanoid trigger was stored as triggered_by NULL, so the trigger check never
    matched and the user could clear their own gate. Publisher and trigger differ
    here, so only the trigger check can refuse this approval."""
    current_user["id"] = NANOID_PUBLISHER
    workflow_id, version_id = await _create_draft(client, "mis29-nanoid-trigger", GATE_STEP)
    published = await client.post(f"/api/v1/workflows/{workflow_id}/versions/{version_id}/publish")
    assert published.status_code == 200, published.text
    db_session.add(_make_agent())
    await db_session.commit()

    current_user["id"] = NANOID_OTHER
    run = await client.post(f"/api/v1/workflows/{workflow_id}/run")
    assert run.status_code == 202, run.text
    resp = await client.post(f"/api/v1/workflows/runs/{run.json()['id']}/steps/gate/approve")
    assert resp.status_code == 403


# ── publish-time validation: package names and probe hosts ───────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "step", [PACKAGE_STEP, NETWORK_STEP, PORT_STEP], ids=["package", "network", "port"],
)
async def test_publish_refuses_an_invalid_package_name_or_probe_host(client, db_session, step):
    """Before the fix publish accepted these; only a run start checked package
    names, and nothing checked hosts. Publish must answer 422 and leave the
    version DRAFT with no current version on the workflow."""
    workflow_id, version_id = await _create_draft(client, "mis29-publish-bad", step)

    resp = await client.post(f"/api/v1/workflows/{workflow_id}/versions/{version_id}/publish")
    assert resp.status_code == 422

    version = await db_session.get(WorkflowVersion, uuid.UUID(version_id))
    await db_session.refresh(version)
    assert version.status == "DRAFT"
    workflow = await db_session.get(Workflow, uuid.UUID(workflow_id))
    await db_session.refresh(workflow)
    assert workflow.current_version_id is None


@pytest.mark.asyncio
async def test_start_run_refuses_a_bad_host_in_a_published_version(
    db_session, fake_cache, fake_storage,
):
    """A PUBLISHED version written before publish validated hosts must still
    not run: start_run walks the same steps and refuses the host with 422
    before a run row exists. The agent is present so only the walk can refuse."""
    db_session.add(_make_agent())
    svc = WorkflowService(db_session, fake_storage)
    workflow = await svc.create_workflow(
        name="mis29-legacy-host",
        yaml_source=_workflow_yaml("mis29-legacy-host", NETWORK_STEP),
        created_by=None,
    )
    version = (await db_session.execute(
        select(WorkflowVersion).where(WorkflowVersion.workflow_id == workflow.id)
    )).scalar_one()
    # Bypasses publish_version on purpose: this is the row a pre-fix publish left behind.
    version.status = "PUBLISHED"
    workflow.current_version_id = version.id
    await db_session.commit()

    with pytest.raises(HTTPException) as exc_info:
        await start_run(
            db_session, fake_cache, fake_storage, workflow.id,
            trigger_type="MANUAL", triggered_by=None,
        )
    assert exc_info.value.status_code == 422
    assert "invalid host" in exc_info.value.detail


# ── network check: host must be a hostname or IP literal ─────────────────────


def _network_step(host: str) -> WorkflowStep:
    config = {"type": "network", "host": host}
    return WorkflowStep(id="probe", type=WorkflowNodeType.CHECK, name="Probe", config=config)


def test_network_check_refuses_a_host_that_is_not_a_hostname_or_ip(tmp_path):
    """The network check quoted host with q() but never validated it, so a value
    that is not a hostname or IP compiled into a ping command. It must raise
    instead, and nothing runs."""
    sentinel = tmp_path / "SENTINEL"
    with pytest.raises(WorkflowRunError):
        _compile_check(_network_step(f"x; touch {sentinel} #"))
    assert not sentinel.exists()


@pytest.mark.parametrize(
    "host, expected",
    [("db.example.com", "ping -c1 -W2 db.example.com"), ("10.0.0.1", "ping -c1 -W2 10.0.0.1")],
)
def test_network_check_still_compiles_a_valid_hostname_or_ip(host, expected):
    assert _compile_check(_network_step(host)) == expected
