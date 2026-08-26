"""Unit tests for api/grpc/agent_service.py's _authenticate_agent() — the
identity gate shared by HeartbeatStream and RenewCertificate (CR-03 +
P11 CRL-lite). Covers: missing cert, CN mismatch, agent-level revocation,
certificate-serial revocation, and revocation-store unavailability."""

import asyncio
import datetime
from types import SimpleNamespace

import grpc
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from lokilinux.api.grpc.agent_service import _AuthGateFailure, _authenticate_agent


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

    def auth_context(self):
        if self._pem is None:
            return {}
        return {"x509_pem_cert": [self._pem]}


def _settings(**overrides):
    defaults = {"certificate_revocation_enabled": True, "certificate_revocation_fail_closed": True}
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class FakeCache:
    def __init__(self, revoked_agents=None):
        self._revoked_agents = set(revoked_agents or ())

    async def get_cached(self, key: str):
        agent_id = key.removeprefix("agent:revoked:")
        return True if agent_id in self._revoked_agents else None


def test_no_certificate_presented_raises_unauthenticated():
    ctx = FakeContext(pem=None)
    with pytest.raises(_AuthGateFailure) as exc_info:
        asyncio.run(_authenticate_agent(ctx, "agent-1", FakeCache(), _settings()))
    assert exc_info.value.code == grpc.StatusCode.UNAUTHENTICATED


def test_agent_id_mismatch_raises_unauthenticated():
    ctx = FakeContext(pem=_cert_pem_with_cn("agent-real"))
    with pytest.raises(_AuthGateFailure) as exc_info:
        asyncio.run(_authenticate_agent(ctx, "agent-spoofed", FakeCache(), _settings()))
    assert exc_info.value.code == grpc.StatusCode.UNAUTHENTICATED


def test_agent_level_revocation_raises_permission_denied():
    ctx = FakeContext(pem=_cert_pem_with_cn("agent-revoked"))
    cache = FakeCache(revoked_agents={"agent-revoked"})
    with pytest.raises(_AuthGateFailure) as exc_info:
        asyncio.run(_authenticate_agent(ctx, "agent-revoked", cache, _settings()))
    assert exc_info.value.code == grpc.StatusCode.PERMISSION_DENIED


def test_certificate_serial_revocation_raises_permission_denied(monkeypatch):
    from lokilinux.api.grpc import agent_service as mod

    async def fake_assert_not_revoked(cache, serial, *, enabled, fail_closed):
        raise mod.CertificateRevoked(str(serial))

    monkeypatch.setattr(mod, "assert_not_revoked", fake_assert_not_revoked)
    ctx = FakeContext(pem=_cert_pem_with_cn("agent-ok"))
    with pytest.raises(_AuthGateFailure) as exc_info:
        asyncio.run(_authenticate_agent(ctx, "agent-ok", FakeCache(), _settings()))
    assert exc_info.value.code == grpc.StatusCode.PERMISSION_DENIED


def test_revocation_store_unavailable_fails_closed(monkeypatch):
    from lokilinux.api.grpc import agent_service as mod

    async def fake_assert_not_revoked(cache, serial, *, enabled, fail_closed):
        raise mod.RevocationUnavailable("redis down")

    monkeypatch.setattr(mod, "assert_not_revoked", fake_assert_not_revoked)
    ctx = FakeContext(pem=_cert_pem_with_cn("agent-ok"))
    with pytest.raises(_AuthGateFailure) as exc_info:
        asyncio.run(_authenticate_agent(ctx, "agent-ok", FakeCache(), _settings(certificate_revocation_fail_closed=True)))
    assert exc_info.value.code == grpc.StatusCode.UNAVAILABLE


def test_valid_matching_unrevoked_certificate_passes(monkeypatch):
    from lokilinux.api.grpc import agent_service as mod

    async def fake_assert_not_revoked(cache, serial, *, enabled, fail_closed):
        return None

    monkeypatch.setattr(mod, "assert_not_revoked", fake_assert_not_revoked)
    ctx = FakeContext(pem=_cert_pem_with_cn("agent-good"))
    asyncio.run(_authenticate_agent(ctx, "agent-good", FakeCache(), _settings()))  # no exception
