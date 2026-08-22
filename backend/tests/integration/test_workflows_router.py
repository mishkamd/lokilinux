"""
Integration tests for /api/v1/workflows — CRUD, versioning, publish gates,
content_hash concurrency, execution (run/cancel/approve/reject), and RBAC.
"""

import uuid
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from lokilinux.models.agent import Agent, AgentStatus
from lokilinux.models.workflow import WorkflowAudit


async def _make_agent(db_session) -> Agent:
    agent = Agent(agent_id=f"router-test-agent-{uuid.uuid4().hex[:8]}", status=AgentStatus.ACTIVE, hostname=f"h-{uuid.uuid4().hex[:6]}")
    db_session.add(agent)
    await db_session.flush()
    await db_session.commit()
    return agent

LINEAR_YAML = """
apiVersion: lokilinux/v1
kind: Workflow
metadata:
  name: linear-three-step
spec:
  targets:
    all: true
  steps:
    - { id: precheck, type: command, name: Preflight, config: { command: "true" } }
    - { id: apply, type: command, name: Apply, config: { command: "true" } }
  edges:
    - { from: precheck, to: apply, on: success }
"""

INVALID_YAML = """
apiVersion: lokilinux/v1
kind: Workflow
metadata:
  name: has-a-cycle
spec:
  targets: { all: true }
  steps:
    - { id: a, type: command, name: A, config: { command: "true" } }
    - { id: b, type: command, name: B, config: { command: "true" } }
  edges:
    - { from: a, to: b, on: success }
    - { from: b, to: a, on: success }
"""


def _yaml_with_name(name: str) -> str:
    return LINEAR_YAML.replace("linear-three-step", name)


@pytest.mark.asyncio
async def test_validate_endpoint_valid_and_invalid(client: AsyncClient):
    resp = await client.post("/api/v1/workflows/validate", json={"yaml": LINEAR_YAML})
    assert resp.status_code == 200
    assert resp.json()["valid"] is True

    resp = await client.post("/api/v1/workflows/validate", json={"yaml": INVALID_YAML})
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is False
    assert any(e["code"] == "CYCLE_DETECTED" for e in body["errors"])


@pytest.mark.asyncio
async def test_get_schema_endpoint(client: AsyncClient):
    resp = await client.get("/api/v1/workflows/schema")
    assert resp.status_code == 200
    assert "properties" in resp.json()


@pytest.mark.asyncio
async def test_create_workflow_from_valid_yaml(client: AsyncClient):
    resp = await client.post("/api/v1/workflows", json={"name": "Linear Three Step", "yaml": _yaml_with_name("create-test-1")})
    assert resp.status_code == 201
    body = resp.json()
    assert body["slug"] == "create-test-1"
    assert body["name"] == "Linear Three Step"
    assert body["current_version_id"] is None  # nothing published yet


@pytest.mark.asyncio
async def test_create_workflow_from_invalid_yaml_is_422(client: AsyncClient):
    resp = await client.post("/api/v1/workflows", json={"name": "Bad", "yaml": INVALID_YAML})
    assert resp.status_code == 422
    assert any(e["code"] == "CYCLE_DETECTED" for e in resp.json()["detail"]["errors"])


@pytest.mark.asyncio
async def test_create_workflow_duplicate_slug_is_409(client: AsyncClient):
    yaml_src = _yaml_with_name("dup-slug-test")
    resp1 = await client.post("/api/v1/workflows", json={"name": "First", "yaml": yaml_src})
    assert resp1.status_code == 201

    resp2 = await client.post("/api/v1/workflows", json={"name": "Second", "yaml": yaml_src})
    assert resp2.status_code == 409


@pytest.mark.asyncio
async def test_create_workflow_writes_audit_row(client: AsyncClient, db_session):
    resp = await client.post("/api/v1/workflows", json={"name": "Audited", "yaml": _yaml_with_name("audited-wf")})
    assert resp.status_code == 201
    workflow_id = resp.json()["id"]

    rows = (await db_session.execute(
        select(WorkflowAudit).where(WorkflowAudit.workflow_id == uuid.UUID(workflow_id))
    )).scalars().all()
    assert len(rows) == 1
    assert rows[0].change_type == "CREATE"


@pytest.mark.asyncio
async def test_get_workflow_includes_first_draft_but_no_current_version(client: AsyncClient):
    create_resp = await client.post("/api/v1/workflows", json={"name": "Detail Test", "yaml": _yaml_with_name("detail-test")})
    workflow_id = create_resp.json()["id"]

    resp = await client.get(f"/api/v1/workflows/{workflow_id}")
    assert resp.status_code == 200
    assert resp.json()["current_version"] is None  # DRAFT, not published


@pytest.mark.asyncio
async def test_get_workflow_404(client: AsyncClient):
    resp = await client.get(f"/api/v1/workflows/{uuid.uuid4()}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_publish_flow_end_to_end(client: AsyncClient):
    create_resp = await client.post("/api/v1/workflows", json={"name": "Publish Test", "yaml": _yaml_with_name("publish-test")})
    workflow_id = create_resp.json()["id"]

    versions_resp = await client.get(f"/api/v1/workflows/{workflow_id}/versions")
    versions = versions_resp.json()["items"]
    assert len(versions) == 1
    version_id = versions[0]["id"]
    assert versions[0]["status"] == "DRAFT"

    publish_resp = await client.post(f"/api/v1/workflows/{workflow_id}/versions/{version_id}/publish")
    assert publish_resp.status_code == 200
    assert publish_resp.json()["status"] == "PUBLISHED"
    assert publish_resp.json()["published_at"] is not None

    detail_resp = await client.get(f"/api/v1/workflows/{workflow_id}")
    assert detail_resp.json()["current_version"]["id"] == version_id
    assert detail_resp.json()["current_version"]["status"] == "PUBLISHED"


@pytest.mark.asyncio
async def test_cannot_publish_twice(client: AsyncClient):
    create_resp = await client.post("/api/v1/workflows", json={"name": "Double Publish", "yaml": _yaml_with_name("double-publish")})
    workflow_id = create_resp.json()["id"]
    version_id = (await client.get(f"/api/v1/workflows/{workflow_id}/versions")).json()["items"][0]["id"]

    first = await client.post(f"/api/v1/workflows/{workflow_id}/versions/{version_id}/publish")
    assert first.status_code == 200

    second = await client.post(f"/api/v1/workflows/{workflow_id}/versions/{version_id}/publish")
    assert second.status_code == 409


@pytest.mark.asyncio
async def test_publishing_a_new_version_archives_the_old_one(client: AsyncClient):
    create_resp = await client.post("/api/v1/workflows", json={"name": "Reversion", "yaml": _yaml_with_name("reversion-test")})
    workflow_id = create_resp.json()["id"]
    v1_id = (await client.get(f"/api/v1/workflows/{workflow_id}/versions")).json()["items"][0]["id"]
    await client.post(f"/api/v1/workflows/{workflow_id}/versions/{v1_id}/publish")

    v2_resp = await client.post(f"/api/v1/workflows/{workflow_id}/versions", json={"yaml": _yaml_with_name("reversion-test")})
    assert v2_resp.status_code == 201
    v2_id = v2_resp.json()["id"]
    assert v2_resp.json()["version"] == 2

    publish2 = await client.post(f"/api/v1/workflows/{workflow_id}/versions/{v2_id}/publish")
    assert publish2.status_code == 200

    versions = (await client.get(f"/api/v1/workflows/{workflow_id}/versions")).json()["items"]
    by_id = {v["id"]: v for v in versions}
    assert by_id[v1_id]["status"] == "ARCHIVED"
    assert by_id[v2_id]["status"] == "PUBLISHED"


@pytest.mark.asyncio
async def test_editing_a_draft_updates_content_hash(client: AsyncClient):
    create_resp = await client.post("/api/v1/workflows", json={"name": "Edit Test", "yaml": _yaml_with_name("edit-test")})
    workflow_id = create_resp.json()["id"]
    version = (await client.get(f"/api/v1/workflows/{workflow_id}/versions")).json()["items"][0]
    version_id, original_hash = version["id"], version["content_hash"]

    resp = await client.put(
        f"/api/v1/workflows/{workflow_id}/versions/{version_id}",
        json={"yaml": _yaml_with_name("edit-test"), "base_content_hash": original_hash},
    )
    assert resp.status_code == 200
    assert resp.json()["content_hash"] == original_hash  # identical content -> identical hash


@pytest.mark.asyncio
async def test_editing_a_draft_with_stale_hash_is_409(client: AsyncClient):
    create_resp = await client.post("/api/v1/workflows", json={"name": "Stale Hash", "yaml": _yaml_with_name("stale-hash-test")})
    workflow_id = create_resp.json()["id"]
    version_id = (await client.get(f"/api/v1/workflows/{workflow_id}/versions")).json()["items"][0]["id"]

    resp = await client.put(
        f"/api/v1/workflows/{workflow_id}/versions/{version_id}",
        json={"yaml": _yaml_with_name("stale-hash-test"), "base_content_hash": "not-the-real-hash"},
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_cannot_edit_a_published_version(client: AsyncClient):
    create_resp = await client.post("/api/v1/workflows", json={"name": "Immutable", "yaml": _yaml_with_name("immutable-test")})
    workflow_id = create_resp.json()["id"]
    version_id = (await client.get(f"/api/v1/workflows/{workflow_id}/versions")).json()["items"][0]["id"]
    await client.post(f"/api/v1/workflows/{workflow_id}/versions/{version_id}/publish")

    resp = await client.put(
        f"/api/v1/workflows/{workflow_id}/versions/{version_id}",
        json={"yaml": _yaml_with_name("immutable-test")},
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_cannot_create_version_with_invalid_yaml(client: AsyncClient):
    create_resp = await client.post("/api/v1/workflows", json={"name": "V2 Invalid", "yaml": _yaml_with_name("v2-invalid-test")})
    workflow_id = create_resp.json()["id"]

    resp = await client.post(f"/api/v1/workflows/{workflow_id}/versions", json={"yaml": INVALID_YAML})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_update_metadata(client: AsyncClient):
    create_resp = await client.post("/api/v1/workflows", json={"name": "Rename Me", "yaml": _yaml_with_name("rename-test")})
    workflow_id = create_resp.json()["id"]

    resp = await client.patch(f"/api/v1/workflows/{workflow_id}", json={"name": "Renamed", "is_enabled": False})
    assert resp.status_code == 200
    assert resp.json()["name"] == "Renamed"
    assert resp.json()["is_enabled"] is False


@pytest.mark.asyncio
async def test_delete_workflow(client: AsyncClient):
    create_resp = await client.post("/api/v1/workflows", json={"name": "To Delete", "yaml": _yaml_with_name("delete-test")})
    workflow_id = create_resp.json()["id"]

    resp = await client.delete(f"/api/v1/workflows/{workflow_id}")
    assert resp.status_code == 204

    resp = await client.get(f"/api/v1/workflows/{workflow_id}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_workflow_with_published_version_does_not_fk_violate(client: AsyncClient):
    """Regression guard for the current_version_id <-> workflow_versions
    self-referencing FK cycle — must be SET NULL on delete, not the
    Postgres default NO ACTION (caught by hand before this test existed)."""
    create_resp = await client.post("/api/v1/workflows", json={"name": "Delete Published", "yaml": _yaml_with_name("delete-published-test")})
    workflow_id = create_resp.json()["id"]
    version_id = (await client.get(f"/api/v1/workflows/{workflow_id}/versions")).json()["items"][0]["id"]
    await client.post(f"/api/v1/workflows/{workflow_id}/versions/{version_id}/publish")

    resp = await client.delete(f"/api/v1/workflows/{workflow_id}")
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_workflows_router_gates_mutations_on_admin_or_operator():
    """Same house pattern as test_policies_router_gates_mutations_on_admin_or_operator
    — every mutating workflows.py endpoint depends on this exact factory."""
    from fastapi import HTTPException

    from lokilinux.auth.dependencies import require_role

    check = require_role("ADMIN", "OPERATOR")

    with pytest.raises(HTTPException) as exc_info:
        await check(user={"id": "u1", "role": "VIEWER"})
    assert exc_info.value.status_code == 403

    for role in ("ADMIN", "OPERATOR"):
        await check(user={"id": "u2", "role": role})  # must not raise


@pytest.mark.asyncio
async def test_oracle_linux_8_to_9_fixture_creates_and_publishes(client: AsyncClient):
    """The plan's own flagship example, exercised end to end through the
    real HTTP router — not just the compiler unit tests."""
    fixture_path = Path(__file__).parent.parent / "unit" / "fixtures" / "workflows" / "oracle-linux-8-to-9.yaml"
    yaml_source = fixture_path.read_text()

    create_resp = await client.post("/api/v1/workflows", json={"name": "Oracle Linux 8 to 9", "yaml": yaml_source})
    assert create_resp.status_code == 201
    workflow_id = create_resp.json()["id"]
    assert create_resp.json()["slug"] == "oracle-linux-8-to-9"
    assert create_resp.json()["severity"] == "CRITICAL"

    version_id = (await client.get(f"/api/v1/workflows/{workflow_id}/versions")).json()["items"][0]["id"]
    publish_resp = await client.post(f"/api/v1/workflows/{workflow_id}/versions/{version_id}/publish")
    assert publish_resp.status_code == 200
    assert publish_resp.json()["status"] == "PUBLISHED"


# ── Execution (Phase 6) ───────────────────────────────────────────────────────

async def _create_and_publish(client: AsyncClient, name: str, slug: str, yaml_template: str = LINEAR_YAML) -> str:
    resp = await client.post("/api/v1/workflows", json={"name": name, "yaml": yaml_template.replace("linear-three-step", slug)})
    assert resp.status_code == 201
    workflow_id = resp.json()["id"]
    version_id = (await client.get(f"/api/v1/workflows/{workflow_id}/versions")).json()["items"][0]["id"]
    publish_resp = await client.post(f"/api/v1/workflows/{workflow_id}/versions/{version_id}/publish")
    assert publish_resp.status_code == 200
    return workflow_id


@pytest.mark.asyncio
async def test_run_without_agents_is_422(client: AsyncClient):
    workflow_id = await _create_and_publish(client, "No Agents Run", "no-agents-run")
    resp = await client.post(f"/api/v1/workflows/{workflow_id}/run")
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_run_unpublished_workflow_is_409(client: AsyncClient):
    resp = await client.post("/api/v1/workflows", json={"name": "Draft Only", "yaml": _yaml_with_name("draft-only-run")})
    workflow_id = resp.json()["id"]

    run_resp = await client.post(f"/api/v1/workflows/{workflow_id}/run")
    assert run_resp.status_code == 409


@pytest.mark.asyncio
async def test_run_dispatches_first_step_as_a_job(client: AsyncClient, db_session):
    await _make_agent(db_session)
    workflow_id = await _create_and_publish(client, "Run Dispatch", "run-dispatch-test")

    resp = await client.post(f"/api/v1/workflows/{workflow_id}/run")
    assert resp.status_code == 202
    run_id = resp.json()["id"]
    assert resp.json()["status"] == "RUNNING"

    detail = await client.get(f"/api/v1/workflows/runs/{run_id}")
    assert detail.status_code == 200
    step_runs = {sr["step_id"]: sr for sr in detail.json()["step_runs"]}
    assert step_runs["precheck"]["status"] == "RUNNING"
    assert step_runs["precheck"]["job_id"] is not None
    assert step_runs["apply"]["status"] == "PENDING"


@pytest.mark.asyncio
async def test_run_appears_in_workflow_runs_list(client: AsyncClient, db_session):
    await _make_agent(db_session)
    workflow_id = await _create_and_publish(client, "Runs List", "runs-list-test")

    run_resp = await client.post(f"/api/v1/workflows/{workflow_id}/run")
    run_id = run_resp.json()["id"]

    list_resp = await client.get(f"/api/v1/workflows/{workflow_id}/runs")
    assert list_resp.status_code == 200
    assert any(r["id"] == run_id for r in list_resp.json()["items"])


@pytest.mark.asyncio
async def test_cancel_run(client: AsyncClient, db_session):
    await _make_agent(db_session)
    workflow_id = await _create_and_publish(client, "Cancel Me", "cancel-me-test")
    run_id = (await client.post(f"/api/v1/workflows/{workflow_id}/run")).json()["id"]

    resp = await client.post(f"/api/v1/workflows/runs/{run_id}/cancel")
    assert resp.status_code == 200
    assert resp.json()["status"] == "CANCELLED"

    second = await client.post(f"/api/v1/workflows/runs/{run_id}/cancel")
    assert second.status_code == 409


@pytest.mark.asyncio
async def test_approve_and_reject_unknown_step_is_404(client: AsyncClient, db_session):
    await _make_agent(db_session)
    workflow_id = await _create_and_publish(client, "No Such Step", "no-such-step-test")
    run_id = (await client.post(f"/api/v1/workflows/{workflow_id}/run")).json()["id"]

    resp = await client.post(f"/api/v1/workflows/runs/{run_id}/steps/does-not-exist/approve")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_approve_a_step_not_waiting_for_approval_is_409(client: AsyncClient, db_session):
    await _make_agent(db_session)
    workflow_id = await _create_and_publish(client, "Not Waiting", "not-waiting-test")
    run_id = (await client.post(f"/api/v1/workflows/{workflow_id}/run")).json()["id"]

    # "precheck" is RUNNING, not WAITING_APPROVAL — and it isn't even an approval step.
    resp = await client.post(f"/api/v1/workflows/runs/{run_id}/steps/precheck/approve")
    assert resp.status_code == 409


# ── Dry run (Phase 8) ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_dry_run_unpublished_workflow_is_409(client: AsyncClient):
    resp = await client.post("/api/v1/workflows", json={"name": "Dry Draft", "yaml": _yaml_with_name("dry-draft-test")})
    workflow_id = resp.json()["id"]

    dry_resp = await client.post(f"/api/v1/workflows/{workflow_id}/dry-run")
    assert dry_resp.status_code == 409


@pytest.mark.asyncio
async def test_dry_run_with_no_agents_reports_zero_matched_not_an_error(client: AsyncClient):
    """Unlike POST .../run (which 422s on zero targets), dry-run is a
    preview — reporting 0 matched is the correct, informative answer."""
    workflow_id = await _create_and_publish(client, "Dry No Agents", "dry-no-agents-test")

    resp = await client.post(f"/api/v1/workflows/{workflow_id}/dry-run")
    assert resp.status_code == 200
    assert resp.json()["targets_matched"] == 0


@pytest.mark.asyncio
async def test_dry_run_creates_no_run_and_no_job(client: AsyncClient, db_session):
    await _make_agent(db_session)
    workflow_id = await _create_and_publish(client, "Dry Real", "dry-real-test")

    resp = await client.post(f"/api/v1/workflows/{workflow_id}/dry-run")
    assert resp.status_code == 200
    body = resp.json()
    assert body["targets_matched"] == 1
    assert len(body["steps"]) == 2
    assert body["estimated_dispatch_seconds"] == 2 * 60  # 2 executable steps * 60s heartbeat
    assert body["requires_approval_at"] == []

    runs_resp = await client.get(f"/api/v1/workflows/{workflow_id}/runs")
    assert runs_resp.json()["items"] == []  # nothing persisted


@pytest.mark.asyncio
async def test_dry_run_reports_every_node_type_as_eligible(client: AsyncClient, db_session):
    """Partea III + Etapa 4: all 14 registry types (notification/webhook
    included, wired last) have a real dispatch path now — dry-run must
    never flag any of them as step_type_not_executable_yet."""
    await _make_agent(db_session)
    yaml_source = """
apiVersion: lokilinux/v1
kind: Workflow
metadata: { name: dry-run-webhook-step-test }
spec:
  targets: { all: true }
  steps:
    - { id: hook, type: webhook, name: Notify, config: {} }
  edges: []
"""
    create_resp = await client.post("/api/v1/workflows", json={"name": "Webhook Step", "yaml": yaml_source})
    workflow_id = create_resp.json()["id"]
    version_id = (await client.get(f"/api/v1/workflows/{workflow_id}/versions")).json()["items"][0]["id"]
    await client.post(f"/api/v1/workflows/{workflow_id}/versions/{version_id}/publish")

    resp = await client.post(f"/api/v1/workflows/{workflow_id}/dry-run")
    assert resp.status_code == 200
    step = resp.json()["steps"][0]
    assert step["eligible"] == 1
    assert step["blocked"] == 0
    assert step["reasons"] == {}
