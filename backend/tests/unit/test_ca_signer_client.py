"""Unit tests for services/ca_signer_client.py — one real round trip over a
UDS-bound uvicorn server (exercises the transport, not just the logic), plus
the unreachable-socket error path."""

import asyncio
import datetime
import threading
import time

import pytest
import uvicorn
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from lokilinux.services import ca_signer_client, ca_signer_service


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


@pytest.fixture
def running_ca_signer(tmp_path, monkeypatch):
    # A real uvicorn.Server actually runs the app's lifespan, which reads
    # CA_KEY_PATH/CA_CERT_PATH from disk — pre-setting _ca_key/_ca_cert
    # directly (as the ASGITransport-based tests do) would just get
    # clobbered the moment lifespan fires. Write real files instead.
    key, cert = _self_signed_ca()
    key_path = tmp_path / "ca.key"
    cert_path = tmp_path / "ca.crt"
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    monkeypatch.setattr(ca_signer_service, "CA_KEY_PATH", str(key_path))
    monkeypatch.setattr(ca_signer_service, "CA_CERT_PATH", str(cert_path))

    sock_path = str(tmp_path / "sign.sock")
    monkeypatch.setenv("CA_SIGNER_SOCKET_PATH", sock_path)

    config = uvicorn.Config(ca_signer_service.app, uds=sock_path, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    else:
        pytest.fail("ca-signer test server did not start in time")

    yield sock_path

    server.should_exit = True
    thread.join(timeout=5)


def test_sign_agent_cert_round_trip(running_ca_signer):  # noqa: ARG001 — fixture used for its side effect
    del running_ca_signer
    cert_pem = asyncio.run(
        ca_signer_client.sign_agent_cert(
            agent_id="agent-roundtrip", public_key_pem=_test_public_key_pem(), validity_days=30,
        )
    )
    cert = x509.load_pem_x509_certificate(cert_pem.encode())
    cn = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value
    assert cn == "agent-roundtrip"


def test_sign_agent_cert_raises_on_unreachable_socket(tmp_path, monkeypatch):
    monkeypatch.setenv("CA_SIGNER_SOCKET_PATH", str(tmp_path / "no-such.sock"))
    with pytest.raises(ca_signer_client.CASignerError):
        asyncio.run(
            ca_signer_client.sign_agent_cert(
                agent_id="agent-1", public_key_pem=_test_public_key_pem(), validity_days=30,
            )
        )
