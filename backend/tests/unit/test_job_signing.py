"""Unit tests for services/job_signing.py — Ed25519 job-envelope signing."""

import base64
import json
import os

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from lokilinux.services.job_signing import JobSigner, verify_fixture


@pytest.fixture()
def key_env(tmp_path, monkeypatch):
    key = Ed25519PrivateKey.generate()
    path = tmp_path / "job_signing.key"
    path.write_bytes(key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ))
    monkeypatch.setenv("JOB_SIGNING_KEY_PATH", str(path))
    return str(path)


@pytest.fixture()
def key_file(tmp_path):
    key = Ed25519PrivateKey.generate()
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    path = tmp_path / "job_signing.key"
    path.write_bytes(pem)
    return str(path)


@pytest.fixture()
def signer(key_env):
    return JobSigner()


def _canonical_unsigned(env: dict) -> bytes:
    unsigned = {k: v for k, v in env.items() if k != "signature"}
    unsigned["signature"] = ""
    return json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()


def test_sign_produces_verifiable_envelope(signer):
    env = signer.sign(
        job_id="j-1", agent_id="a-1", tenant_id="t-1", job_type="SERVICE",
        payload={"action": "restart"}, policy_id="p-1", risk_level="MEDIUM",
        requested_capabilities=["SERVICE_CONTROL"], now=1780000000,
    )
    assert verify_fixture(signer.public_key_b64(), env)
    assert env["expires_at"] == 1780000300
    assert env["nonce"]


def test_signature_covers_all_fields_except_signature(signer):
    env = signer.sign("j-1", "a-1", "", "SERVICE", {}, now=1780000000)
    # empty optionals must be PRESENT (contract with Go UnsignedBytes);
    # risk_level keeps its documented default
    for field, empty in (("tenant_id", ""), ("policy_id", ""), ("payload", {})):
        assert field in env and env[field] == empty
    assert env["risk_level"] == "HIGH"
    assert isinstance(env["requested_capabilities"], list)

    pub = Ed25519PrivateKey.generate().public_key()  # wrong key
    from cryptography.exceptions import InvalidSignature

    with pytest.raises(InvalidSignature):
        raw = base64.b64decode(env["signature"])
        pub.verify(raw, b"tampered")


def test_tampered_payload_fails_verification(signer):
    env = signer.sign("j-1", "a-1", "t", "SERVICE", {"x": 1}, now=1780000000)
    env["payload"]["x"] = 999
    assert not verify_fixture(signer.public_key_b64(), env)


def test_raw_seed_key_supported(tmp_path, monkeypatch):
    seed = os.urandom(32)
    p = tmp_path / "raw.key"
    p.write_bytes(seed)
    monkeypatch.setenv("JOB_SIGNING_KEY_PATH", str(p))
    s1 = JobSigner()
    env = s1.sign("j", "a", "", "SERVICE", {})
    assert len(base64.b64decode(s1.public_key_b64())) == 32
    assert verify_fixture(s1.public_key_b64(), env)


def _counter_total(counter) -> float:
    return sum(s.value for m in counter.collect() for s in m.samples if s.name.endswith("_total"))


def test_sign_increments_kms_success_metric(signer):
    from lokilinux import metrics

    before = _counter_total(metrics.kms_sign_success_total)
    signer.sign("j-1", "a-1", "t", "SERVICE", {})
    assert _counter_total(metrics.kms_sign_success_total) == before + 1


def test_sign_failure_increments_kms_failure_metric(signer, key_env):
    from lokilinux import metrics

    before = _counter_total(metrics.kms_sign_failure_total)
    os.remove(key_env)  # provider now fails to load the key on next use
    with pytest.raises(Exception):
        signer.sign("j-1", "a-1", "t", "SERVICE", {})
    assert _counter_total(metrics.kms_sign_failure_total) == before + 1


def test_rejects_non_ed25519_key(tmp_path, monkeypatch):
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    p = tmp_path / "rsa.key"
    p.write_bytes(pem)
    monkeypatch.setenv("JOB_SIGNING_KEY_PATH", str(p))
    with pytest.raises(Exception):  # ProviderUnavailable wraps the ValueError
        JobSigner()
