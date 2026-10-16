"""storage.read matrix — every route gated by require_permission("storage.read").

ADMIN/OPERATOR/AUDITOR clear the permission dependency and reach the handler
(404 for a random id; 200 for the two list routes). VIEWER/USER are refused
before the handler runs, with the permission-specific detail. The playbook and
ansible-role detail routes are open to every role: they return metadata and
blank the stored content for roles without storage.read (see the redaction
tests). The plugin row is enabled for the matrix, so a plugin-gate 403 can
never masquerade as a permission denial.
"""

import uuid

import pytest
from sqlalchemy import select

from lokilinux.auth.dependencies import get_current_user
from lokilinux.auth.permissions import PERMISSIONS
from lokilinux.models.audit import AuditLog
from lokilinux.models.job import Job
from lokilinux.models.plugin import Plugin

ANSIBLE_PLUGIN = "ansible-automation"
WORKFLOW_YAML = """
apiVersion: lokilinux/v1
kind: Workflow
metadata:
  name: redaction-probe
spec:
  targets:
    all: true
  steps:
    - { id: precheck, type: command, name: Preflight, config: { command: "true" } }
    - { id: apply, type: command, name: Apply, config: { command: "true" } }
  edges:
    - { from: precheck, to: apply, on: success }
"""
ALLOWED_ROLES = ("ADMIN", "OPERATOR", "AUDITOR")
DENIED_ROLES = ("VIEWER", "USER")
DENIED_DETAIL = "Missing permission: storage.read"

# (method, path template, status an allowed role gets for a random id)
ROUTES = [
    ("GET", "/api/v1/storage/objects", 200),
    ("GET", "/api/v1/storage/objects/{id}", 404),
    ("GET", "/api/v1/storage/objects/{id}/download", 404),
    ("POST", "/api/v1/storage/objects/{id}/verify", 404),
    ("GET", "/api/v1/compliance/reports/{id}/download", 404),
    ("GET", "/api/v1/workflows/{id}/versions", 200),
]


def test_storage_read_roles():
    assert PERMISSIONS["storage.read"] == frozenset({"OPERATOR", "AUDITOR"})


async def _set_ansible_plugin(db_session, enabled: bool) -> None:
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
    # ponytail: reaches the app through the httpx transport; conftest's client
    # fixture doesn't expose it. Restored on teardown as the override contract requires.
    app = client._transport.app
    saved = app.dependency_overrides.get(get_current_user)

    def _set(role: str) -> str:
        user_id = str(uuid.uuid4())
        user = {"id": user_id, "role": role, "username": "t"}
        app.dependency_overrides[get_current_user] = lambda: user
        return user_id

    yield _set
    if saved is None:
        app.dependency_overrides.pop(get_current_user, None)
    else:
        app.dependency_overrides[get_current_user] = saved


@pytest.fixture
async def ansible_plugin_enabled(db_session):
    await _set_ansible_plugin(db_session, True)


@pytest.mark.parametrize("role", ALLOWED_ROLES + DENIED_ROLES)
@pytest.mark.parametrize("method,path,allowed_status", ROUTES)
async def test_storage_read_matrix(
    method, path, allowed_status, role, as_role, ansible_plugin_enabled, client
):
    as_role(role)
    resp = await client.request(method, path.format(id=uuid.uuid4()))
    if role in ALLOWED_ROLES:
        assert resp.status_code == allowed_status, f"{role} {method} {path}: {resp.text}"
    else:
        assert resp.status_code == 403, f"{role} {method} {path}: {resp.text}"
        assert resp.json()["detail"] == DENIED_DETAIL


async def test_viewer_denial_writes_rbac_audit_row(as_role, client, db_session):
    user_id = as_role("VIEWER")
    resp = await client.get("/api/v1/storage/objects")
    assert resp.status_code == 403

    rows = (
        (
            await db_session.execute(
                select(AuditLog).where(
                    AuditLog.action == "rbac.denied", AuditLog.resource_id == "storage.read"
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].user_id == user_id
    assert rows[0].changes == {"role": "VIEWER"}
    assert rows[0].status == "failure"


async def test_disabled_plugin_reports_plugin_gate_not_permission(as_role, client, db_session):
    # Shows the matrix's exact-detail check is what separates the two 403s:
    # with the plugin off, even ADMIN gets the plugin detail.
    await _set_ansible_plugin(db_session, False)
    as_role("ADMIN")
    resp = await client.get(f"/api/v1/playbooks/{uuid.uuid4()}")
    assert resp.status_code == 403
    assert resp.json()["detail"] == f"Plugin '{ANSIBLE_PLUGIN}' is not enabled"


# ── Content redaction on read routes (no refusal: the metadata stays visible) ──


async def _published_workflow(client, as_role) -> str:
    as_role("ADMIN")
    created = await client.post(
        "/api/v1/workflows",
        json={"name": f"probe-{uuid.uuid4().hex[:8]}", "yaml": WORKFLOW_YAML},
    )
    assert created.status_code == 201
    wf_id = created.json()["id"]
    version_id = (await client.get(f"/api/v1/workflows/{wf_id}/versions")).json()["items"][0]["id"]
    published = await client.post(f"/api/v1/workflows/{wf_id}/versions/{version_id}/publish")
    assert published.status_code == 200
    return wf_id


@pytest.mark.parametrize("role", ALLOWED_ROLES + DENIED_ROLES)
async def test_workflow_detail_blanks_content_without_storage_read(role, as_role, client):
    wf_id = await _published_workflow(client, as_role)
    as_role(role)
    resp = await client.get(f"/api/v1/workflows/{wf_id}")
    assert resp.status_code == 200, resp.text
    current = resp.json()["current_version"]
    assert current["status"] == "PUBLISHED"
    assert current["content_hash"]  # metadata survives for every caller
    if role in ALLOWED_ROLES:
        assert "apiVersion" in current["yaml_source"]
        assert current["graph"] != {}
    else:
        assert current["yaml_source"] == ""
        assert current["graph"] == {}


async def _ansible_job(db_session, template_id: str) -> Job:
    job = Job(
        name="Ansible: redaction-probe",
        job_type="ANSIBLE_PLAYBOOK",
        target_servers={"agent_ids": []},
        parameters={
            "playbook_id": str(uuid.uuid4()),
            "playbook_content": "- hosts: all\n  tasks: []\n",
            "roles": {"r1": {"tasks/main.yml": "- debug: msg=x\n"}},
            "extra_vars": {"k": "v"},
            "template_id": template_id,
        },
    )
    db_session.add(job)
    await db_session.flush()
    return job


def _assert_content_keys(params: dict, role: str) -> None:
    assert params["extra_vars"] == {"k": "v"}  # non-content keys always survive
    if role in ALLOWED_ROLES:
        assert params["playbook_content"].startswith("- hosts")
        assert "r1" in params["roles"]
    else:
        assert "playbook_content" not in params
        assert "roles" not in params


@pytest.mark.parametrize("role", ALLOWED_ROLES + DENIED_ROLES)
async def test_job_reads_redact_ansible_content_params(
    role, as_role, client, db_session, ansible_plugin_enabled
):
    template_id = str(uuid.uuid4())
    job = await _ansible_job(db_session, template_id)
    as_role(role)

    detail = await client.get(f"/api/v1/jobs/{job.id}")
    assert detail.status_code == 200, detail.text
    _assert_content_keys(detail.json()["parameters"], role)

    listing = await client.get("/api/v1/jobs")
    assert listing.status_code == 200, listing.text
    row = next(j for j in listing.json()["items"] if j["id"] == str(job.id))
    _assert_content_keys(row["parameters"], role)

    history = await client.get(f"/api/v1/playbook-templates/{template_id}/history")
    assert history.status_code == 200, history.text
    _assert_content_keys(history.json()[0]["parameters"], role)


async def test_redaction_does_not_mutate_stored_job(
    as_role, client, db_session, ansible_plugin_enabled
):
    job = await _ansible_job(db_session, str(uuid.uuid4()))
    as_role("VIEWER")
    assert (await client.get(f"/api/v1/jobs/{job.id}")).status_code == 200
    assert "playbook_content" in job.parameters  # ORM row untouched
    assert "roles" in job.parameters


PLAYBOOK_BODY = {"name": "redaction-probe-playbook", "content": "- hosts: all\n  tasks: []\n"}
ROLE_BODY = {"name": "redaction-probe-role", "files": {"tasks/main.yml": "- debug: msg=hi\n"}}


@pytest.mark.parametrize("role", ALLOWED_ROLES + DENIED_ROLES)
async def test_playbook_and_role_detail_open_to_every_role(
    role, as_role, client, ansible_plugin_enabled
):
    # Random id: the handler's own 404 proves the dependency let the request through.
    as_role(role)
    for path in ("/api/v1/playbooks/{id}", "/api/v1/ansible-roles/{id}"):
        resp = await client.get(path.format(id=uuid.uuid4()))
        assert resp.status_code == 404, f"{role} {path}: {resp.text}"


@pytest.mark.parametrize("role", ALLOWED_ROLES + DENIED_ROLES)
async def test_playbook_content_blanked_without_storage_read(
    role, as_role, client, ansible_plugin_enabled
):
    as_role("OPERATOR")
    created = await client.post("/api/v1/playbooks", json=PLAYBOOK_BODY)
    assert created.status_code == 201, created.text

    as_role(role)
    resp = await client.get(f"/api/v1/playbooks/{created.json()['id']}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == PLAYBOOK_BODY["name"]
    expected = PLAYBOOK_BODY["content"] if role in ALLOWED_ROLES else ""
    assert resp.json()["content"] == expected


@pytest.mark.parametrize("role", ALLOWED_ROLES + DENIED_ROLES)
async def test_ansible_role_files_blanked_without_storage_read(
    role, as_role, client, ansible_plugin_enabled
):
    as_role("OPERATOR")
    created = await client.post("/api/v1/ansible-roles", json=ROLE_BODY)
    assert created.status_code == 201, created.text

    as_role(role)
    resp = await client.get(f"/api/v1/ansible-roles/{created.json()['id']}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == ROLE_BODY["name"]
    expected = ROLE_BODY["files"] if role in ALLOWED_ROLES else {}
    assert resp.json()["files"] == expected
