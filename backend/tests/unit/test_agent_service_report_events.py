"""Unit tests for AgentServicer.ReportEvents (Phase G2, task G2-5).

Covers the concrete idempotency requirement (agent-issued event_id survives
to the published NATS message unchanged), auth-gate-before-publish ordering,
and malformed-batch resilience (one bad batch doesn't kill the stream).
"""

import base64
import datetime
import gzip
import json
from types import SimpleNamespace

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from lokilinux.api.grpc.agent_service import AgentServicer


def _cert_pem_with_cn(cn: str) -> bytes:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(12345)
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=1))
        .sign(key, hashes.SHA256())
    )
    return cert.public_bytes(serialization.Encoding.PEM)


class FakeContext:
    def __init__(self, pem: bytes | None):
        self._pem = pem
        self.aborted = None

    def auth_context(self):
        if self._pem is None:
            return {}
        return {"x509_pem_cert": [self._pem]}

    async def abort(self, code, detail):
        self.aborted = (code, detail)
        raise _Aborted()


class _Aborted(Exception):
    pass


class FakeCache:
    async def get_cached(self, key: str):
        return None


class FakeNats:
    def __init__(self):
        self.published: list[tuple[str, dict]] = []

    async def publish(self, subject: str, data: bytes):
        self.published.append((subject, json.loads(data)))


def _settings():
    return SimpleNamespace(
        certificate_revocation_enabled=False, certificate_revocation_fail_closed=True
    )


def _batch(agent_id: str, records: list[dict]) -> SimpleNamespace:
    raw = gzip.compress(json.dumps(records).encode())
    return SimpleNamespace(
        agent_id=agent_id, batch_id="b1", events_gzip=base64.b64encode(raw).decode()
    )


async def _run(servicer, context, batches):
    async def gen():
        for b in batches:
            yield b

    return await servicer.ReportEvents(gen(), context)


@pytest.mark.asyncio
async def test_auth_failure_aborts_before_publish(monkeypatch):
    import lokilinux.config as config_mod

    monkeypatch.setattr(config_mod, "get_settings", lambda: _settings())
    nats = FakeNats()
    servicer = AgentServicer(db_factory=None, cache=FakeCache(), nats=nats)
    context = FakeContext(pem=_cert_pem_with_cn("agent-real"))

    with pytest.raises(_Aborted):
        await _run(servicer, context, [_batch("agent-spoofed", [{"type": "t", "event_id": "e1"}])])

    assert context.aborted is not None
    assert nats.published == []


@pytest.mark.asyncio
async def test_batch_preserves_agent_issued_event_id(monkeypatch):
    import lokilinux.config as config_mod

    monkeypatch.setattr(config_mod, "get_settings", lambda: _settings())
    nats = FakeNats()
    servicer = AgentServicer(db_factory=None, cache=FakeCache(), nats=nats)
    context = FakeContext(pem=_cert_pem_with_cn("agent-1"))

    records = [
        {"type": "kernel.panic", "severity": "CRITICAL", "event_id": "agent-issued-1"},
        {"type": "storage.io_error", "severity": "ERROR", "event_id": "agent-issued-2"},
    ]
    result = await _run(servicer, context, [_batch("agent-1", records)])

    assert result["accepted"] is True
    assert result["events_accepted"] == 2
    assert len(nats.published) == 2
    sent_ids = {msg["event_id"] for _, msg in nats.published}
    assert sent_ids == {"agent-issued-1", "agent-issued-2"}


@pytest.mark.asyncio
async def test_malformed_batch_skipped_stream_continues(monkeypatch):
    import lokilinux.config as config_mod

    monkeypatch.setattr(config_mod, "get_settings", lambda: _settings())
    nats = FakeNats()
    servicer = AgentServicer(db_factory=None, cache=FakeCache(), nats=nats)
    context = FakeContext(pem=_cert_pem_with_cn("agent-1"))

    bad_batch = SimpleNamespace(
        agent_id="agent-1", batch_id="bad", events_gzip="not-valid-base64-or-gzip"
    )
    good_batch = _batch("agent-1", [{"type": "service.failed", "event_id": "e-good"}])

    result = await _run(servicer, context, [bad_batch, good_batch])

    assert result["accepted"] is True
    assert result["events_accepted"] == 1
    assert len(nats.published) == 1
    assert nats.published[0][1]["event_id"] == "e-good"
