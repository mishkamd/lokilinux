"""
Integration tests for POST /api/v1/agents/{id}/revoke — the REST side of the
agent identity deny-list. Enforcement is the gRPC identity gate
(api/grpc/agent_service.py::_authenticate_agent), so the heartbeat tests drive
HeartbeatStream through that real gate. Job pickup only happens inside
HeartbeatStream (get_pending_jobs), so a refused heartbeat means no jobs.
"""

import datetime
import uuid
from types import SimpleNamespace

import grpc
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from httpx import AsyncClient
from sqlalchemy import select

from lokilinux.api.grpc.agent_service import AgentServicer
from lokilinux.models.agent import Agent, AgentStatus
from lokilinux.models.audit import AuditLog


class _AbortError(Exception):
    def __init__(self, code, detail):
        super().__init__(detail)
        self.code = code
        self.detail = detail


class _StreamContext:
    def __init__(self, pem: bytes):
        self._pem = pem

    def auth_context(self):
        return {"x509_pem_cert": [self._pem]}

    def peer(self):
        return "ipv4:10.0.0.5:5555"

    async def abort(self, code, detail):
        raise _AbortError(code, detail)


class _RecordingFactory:
    """db_factory stand-in. Entering it means the heartbeat got past the gate
    and reached the DB (where get_pending_jobs runs). The raise is swallowed by
    HeartbeatStream's generic except, which is by design."""

    def __init__(self):
        self.entered = False

    def __call__(self):
        return self

    async def __aenter__(self):
        self.entered = True
        raise RuntimeError("stop after gate")

    async def __aexit__(self, *exc):
        return False


def _cert_pem(cn: str) -> bytes:
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=1))
        .sign(key, hashes.SHA256())
    )
    return cert.public_bytes(serialization.Encoding.PEM)


async def _heartbeat(servicer: AgentServicer, agent_id: str, pem: bytes) -> None:
    async def _requests():
        yield SimpleNamespace(agent_id=agent_id)

    async for _ in servicer.HeartbeatStream(_requests(), _StreamContext(pem)):
        pass


async def _make_agent(db_session) -> Agent:
    agent = Agent(agent_id=str(uuid.uuid4()), status=AgentStatus.ACTIVE, hostname="rev-01")
    db_session.add(agent)
    await db_session.flush()
    return agent


@pytest.mark.asyncio
async def test_admin_revoke_blocks_heartbeat_and_job_pickup(
    client: AsyncClient, db_session, fake_cache
):
    agent = await _make_agent(db_session)
    await db_session.commit()
    pem = _cert_pem(agent.agent_id)

    before = _RecordingFactory()
    servicer = AgentServicer(db_factory=before, cache=fake_cache, nats=None)
    await _heartbeat(servicer, agent.agent_id, pem)
    assert before.entered is True  # control: unrevoked agent passes the gate

    resp = await client.post(f"/api/v1/agents/{agent.id}/revoke")
    assert resp.status_code == 200

    after = _RecordingFactory()
    servicer = AgentServicer(db_factory=after, cache=fake_cache, nats=None)
    with pytest.raises(_AbortError) as ei:
        await _heartbeat(servicer, agent.agent_id, pem)
    assert ei.value.code == grpc.StatusCode.PERMISSION_DENIED
    assert after.entered is False  # refused before any DB work, so no job pickup


@pytest.mark.asyncio
async def test_revoke_writes_audit_row_with_actor(client: AsyncClient, db_session, current_user):
    actor = str(uuid.uuid4())
    current_user.update(id=actor, role="ADMIN")
    agent = await _make_agent(db_session)
    await db_session.commit()

    resp = await client.post(f"/api/v1/agents/{agent.id}/revoke")
    assert resp.status_code == 200

    rows = (
        (
            await db_session.execute(
                select(AuditLog).where(
                    AuditLog.action == "agent.revoked",
                    AuditLog.resource_id == str(agent.id),
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].user_id == actor


@pytest.mark.asyncio
async def test_operator_cannot_revoke(client: AsyncClient, db_session, current_user, fake_cache):
    current_user["role"] = "OPERATOR"
    agent = await _make_agent(db_session)
    await db_session.commit()

    resp = await client.post(f"/api/v1/agents/{agent.id}/revoke")
    assert resp.status_code == 403
    assert await fake_cache.get_cached(f"agent:revoked:{agent.agent_id}") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_id", [str(uuid.uuid4()), "not-a-uuid"])
async def test_revoke_unknown_agent_is_404(client: AsyncClient, bad_id):
    resp = await client.post(f"/api/v1/agents/{bad_id}/revoke")
    assert resp.status_code == 404
