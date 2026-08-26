"""Unit tests for services/ca_signer_service.py's /sign endpoint.

Bypasses the FastAPI lifespan (ASGI lifespan isn't wired through
httpx.ASGITransport by default) by monkeypatching the module's _ca_key/
_ca_cert globals directly with a throwaway test CA — the lifespan itself is
a few lines of file-reading, not what's worth testing here.
"""

import asyncio
import datetime

import httpx
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from lokilinux.services import ca_signer_service


def _self_signed_ca():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Test-CA")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=1))
        .sign(key, hashes.SHA256())
    )
    return key, cert


def _test_public_key_pem() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode()


def _sign(payload: dict) -> httpx.Response:
    transport = httpx.ASGITransport(app=ca_signer_service.app)

    async def _call():
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.post("/sign", json=payload)

    return asyncio.run(_call())


def _with_ready_ca(monkeypatch):
    key, cert = _self_signed_ca()
    monkeypatch.setattr(ca_signer_service, "_ca_key", key)
    monkeypatch.setattr(ca_signer_service, "_ca_cert", cert)


def test_sign_returns_cert_with_requested_cn_and_validity(monkeypatch):
    _with_ready_ca(monkeypatch)
    resp = _sign({
        "agent_id": "agent-abc123",
        "public_key_pem": _test_public_key_pem(),
        "validity_days": 30,
    })
    assert resp.status_code == 200
    cert = x509.load_pem_x509_certificate(resp.json()["cert_pem"].encode())
    cn = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value
    assert cn == "agent-abc123"
    delta = cert.not_valid_after_utc - cert.not_valid_before_utc
    assert delta.days in (29, 30)  # not_valid_before backdated slightly by cryptography


def test_sign_rejects_invalid_public_key(monkeypatch):
    _with_ready_ca(monkeypatch)
    resp = _sign({"agent_id": "agent-1", "public_key_pem": "not a key", "validity_days": 30})
    assert resp.status_code == 400


def test_sign_rejects_validity_days_over_ceiling(monkeypatch):
    _with_ready_ca(monkeypatch)
    resp = _sign({
        "agent_id": "agent-1",
        "public_key_pem": _test_public_key_pem(),
        "validity_days": ca_signer_service.MAX_VALIDITY_DAYS + 1,
    })
    assert resp.status_code == 422


def test_sign_rejects_empty_agent_id(monkeypatch):
    _with_ready_ca(monkeypatch)
    resp = _sign({"agent_id": "", "public_key_pem": _test_public_key_pem(), "validity_days": 30})
    assert resp.status_code == 422


def test_sign_returns_503_before_ca_material_loaded(monkeypatch):
    monkeypatch.setattr(ca_signer_service, "_ca_key", None)
    monkeypatch.setattr(ca_signer_service, "_ca_cert", None)
    resp = _sign({"agent_id": "agent-1", "public_key_pem": _test_public_key_pem(), "validity_days": 30})
    assert resp.status_code == 503
