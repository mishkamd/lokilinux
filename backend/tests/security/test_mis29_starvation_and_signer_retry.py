"""MIS-29 held-job path, two defects:

  - a privileged job held for a signing failure stays PENDING, so held jobs fill the
    get_pending_jobs window and starve the non-privileged jobs queued behind them;
  - a failed signer initialisation was never retried, so every privileged job stayed
    held until the process restarted.

Fixtures (db_session, fake_cache, fake_nats) come from tests/conftest.py.
"""

import contextlib
import time
import uuid

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

# Same-directory helpers: the held-job heartbeat driver, the broken signer, and the
# real CA + agent cert used by the CR-03 suite.
from test_mis29_root_held_jobs import _heartbeat, _state
from test_mis29_signing import _BrokenSigner
from test_security_p0 import _issue_agent_cert, _make_ca

from lokilinux.api.grpc.agent_service import AgentServicer
from lokilinux.models.agent import Agent, AgentStatus
from lokilinux.services import job_envelope
from lokilinux.services.job_service import JobService


async def _agent_with_jobs(db_session, fake_cache, fake_nats, tmp_path, monkeypatch, *, held, sent):
    """One agent with `held` privileged SERVICE jobs (signing broken, so held) created
    before `sent` non-privileged INVENTORY_SCAN jobs. Returns (servicer, wire_id, pem,
    held_jobs, sent_jobs)."""
    _, ca_key, ca_cert = _make_ca(tmp_path)
    wire_id = str(uuid.uuid4())
    pem = _issue_agent_cert(ca_key, ca_cert, wire_id)
    agent = Agent(
        agent_id=wire_id, status=AgentStatus.ACTIVE, hostname=f"host-{uuid.uuid4().hex[:8]}"
    )
    db_session.add(agent)
    await db_session.flush()

    svc = JobService(db_session, fake_cache, fake_nats)
    held_jobs = [
        await svc.create_job(
            name=f"held-{i}", job_type="SERVICE",
            target_servers={"agent_ids": [str(agent.id)]},
            parameters={"service_name": "nginx"},
        )
        for i in range(held)
    ]
    sent_jobs = [
        await svc.create_job(
            name=f"sent-{i}", job_type="INVENTORY_SCAN",
            target_servers={"agent_ids": [str(agent.id)]},
        )
        for i in range(sent)
    ]
    monkeypatch.setattr(job_envelope, "_get_signer", lambda: _BrokenSigner())

    @contextlib.asynccontextmanager
    async def session_factory():
        yield db_session

    servicer = AgentServicer(db_factory=session_factory, cache=fake_cache, nats=fake_nats)
    return servicer, wire_id, pem, held_jobs, sent_jobs


def _pem_private_key() -> bytes:
    return Ed25519PrivateKey.generate().private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


@pytest.mark.asyncio
async def test_ten_held_jobs_do_not_starve_a_non_privileged_job(
    db_session, fake_cache, fake_nats, tmp_path, monkeypatch
):
    """Ten privileged jobs held for a signing failure fill the 10-row pending window.
    The non-privileged job queued behind them must still go out in this heartbeat."""
    servicer, wire_id, pem, held, sent = await _agent_with_jobs(
        db_session, fake_cache, fake_nats, tmp_path, monkeypatch, held=10, sent=1
    )

    dispatched = await _heartbeat(servicer, wire_id, pem)

    assert str(sent[0].id) in dispatched
    for job in held:
        assert str(job.id) not in dispatched
        result, _ = await _state(db_session, job)
        assert result.status == "PENDING"


@pytest.mark.asyncio
async def test_heartbeat_still_sends_at_most_ten_jobs(
    db_session, fake_cache, fake_nats, tmp_path, monkeypatch
):
    """Asking again past held jobs must not lift the 10-per-heartbeat cap: one held job
    plus twelve non-privileged jobs sends exactly ten."""
    servicer, wire_id, pem, held, sent = await _agent_with_jobs(
        db_session, fake_cache, fake_nats, tmp_path, monkeypatch, held=1, sent=12
    )

    dispatched = await _heartbeat(servicer, wire_id, pem)

    assert len(dispatched) == 10
    assert str(held[0].id) not in dispatched


def test_failed_signer_init_is_retried_after_backoff(monkeypatch, tmp_path):
    """A signer whose first initialisation failed is retried once the 60s backoff has
    passed. Before the fix it stayed None until the process restarted, which held every
    privileged job for that whole time. A successful init stays cached."""
    now = [1000.0]
    monkeypatch.setattr(time, "monotonic", lambda: now[0])
    # Backoff deadline is module state; restore it so it cannot leak into later tests.
    monkeypatch.setattr(job_envelope, "_signer_retry_at", 0.0, raising=False)
    monkeypatch.setattr(job_envelope, "_signer_instance", None)
    monkeypatch.setattr(job_envelope, "_signer_init_done", False)
    key = tmp_path / "job_signing.key"
    key.write_bytes(b"not a key")
    monkeypatch.setenv("JOB_SIGNING_KEY_PATH", str(key))
    monkeypatch.delenv("LOKILINUX_KEYS_DIR", raising=False)
    monkeypatch.delenv("JOB_SIGNING_ENVELOPES", raising=False)

    assert job_envelope._get_signer() is None  # first init fails on the unreadable key

    key.write_bytes(_pem_private_key())  # operator replaces the key
    now[0] += 30
    assert job_envelope._get_signer() is None  # still inside the backoff window

    now[0] += 31  # 61s after the failure
    signer = job_envelope._get_signer()
    assert signer is not None

    key.write_bytes(b"corrupted later")  # a cached signer must not be dropped by this
    now[0] += 3600
    assert job_envelope._get_signer() is signer
