"""Unit tests for AgentServicer.SyncPolicy (Phase G2, task G2-5) and its
_get_collector_policy helper — the global, settings-table-backed collector
policy read path."""

import datetime
import json
from types import SimpleNamespace

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from lokilinux.api.grpc.agent_service import AgentServicer, _get_collector_policy


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


class FakeRow:
    def __init__(self, value):
        self.value = value


class FakeResult:
    def __init__(self, row):
        self._row = row

    def scalar_one_or_none(self):
        return self._row


class FakeDB:
    """Just enough of an AsyncSession for _get_collector_policy's single
    select — returns a fixed row regardless of the query, this helper only
    ever queries one key."""

    def __init__(self, stored_value: str | None):
        self._stored_value = stored_value

    async def execute(self, _stmt):
        return FakeResult(FakeRow(self._stored_value) if self._stored_value is not None else None)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _settings():
    return SimpleNamespace(
        certificate_revocation_enabled=False, certificate_revocation_fail_closed=True
    )


@pytest.mark.asyncio
async def test_get_collector_policy_defaults_when_unset():
    policy = await _get_collector_policy(FakeDB(stored_value=None))
    assert policy == {"version": "0", "collectors": {}}


@pytest.mark.asyncio
async def test_get_collector_policy_parses_stored_json():
    stored = json.dumps(
        {"version": "3", "collectors": {"cpu": {"enabled": True, "interval_seconds": 30}}}
    )
    policy = await _get_collector_policy(FakeDB(stored_value=stored))
    assert policy["version"] == "3"
    assert policy["collectors"]["cpu"]["enabled"] is True


@pytest.mark.asyncio
async def test_get_collector_policy_falls_back_on_corrupt_json():
    policy = await _get_collector_policy(FakeDB(stored_value="{not json"))
    assert policy == {"version": "0", "collectors": {}}


@pytest.mark.asyncio
async def test_sync_policy_auth_failure_aborts(monkeypatch):
    import lokilinux.config as config_mod

    monkeypatch.setattr(config_mod, "get_settings", lambda: _settings())
    servicer = AgentServicer(
        db_factory=lambda: FakeDB(stored_value=None), cache=FakeCache(), nats=None
    )
    context = FakeContext(pem=_cert_pem_with_cn("agent-real"))
    request = SimpleNamespace(agent_id="agent-spoofed", current_version="0")

    with pytest.raises(_Aborted):
        await servicer.SyncPolicy(request, context)

    assert context.aborted is not None


@pytest.mark.asyncio
async def test_sync_policy_returns_stored_collector_config(monkeypatch):
    import lokilinux.config as config_mod

    monkeypatch.setattr(config_mod, "get_settings", lambda: _settings())
    stored = json.dumps({"version": "5", "collectors": {"disk": {"enabled": False}}})
    servicer = AgentServicer(
        db_factory=lambda: FakeDB(stored_value=stored), cache=FakeCache(), nats=None
    )
    context = FakeContext(pem=_cert_pem_with_cn("agent-1"))
    request = SimpleNamespace(agent_id="agent-1", current_version="0")

    result = await servicer.SyncPolicy(request, context)

    assert result["version"] == "5"
    assert result["collectors"]["disk"]["enabled"] is False
