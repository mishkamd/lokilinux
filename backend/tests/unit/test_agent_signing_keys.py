"""Tests for JobSigner.public_keys() and GET /api/v1/agent/signing-keys —
the versioned map installers write into agent.yaml security.signing_pub_keys
so a KMS rotation reaches agents enrolling after it, not just before."""

import base64

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from httpx import AsyncClient

from lokilinux.kms import KeyManager, get_provider
from lokilinux.services import job_envelope
from lokilinux.services.job_signing import JobSigner


def _seed_key(path):
    key = Ed25519PrivateKey.generate()
    with open(path, "wb") as f:
        f.write(
            key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )


# ── JobSigner.public_keys() — unit level ────────────────────────────────────


def test_public_keys_legacy_layout(tmp_path, monkeypatch):
    key_path = tmp_path / "job_signing.key"
    _seed_key(key_path)
    monkeypatch.setenv("JOB_SIGNING_KEY_PATH", str(key_path))
    signer = JobSigner()  # no provider/keys_dir => legacy, _key_manager is None
    keys = signer.public_keys()
    assert set(keys) == {"1"}
    assert len(base64.b64decode(keys["1"])) == 32


def test_public_keys_versioned_excludes_retired(tmp_path):
    keys_dir = tmp_path / "keys"
    legacy_path = tmp_path / "job_signing.key"
    _seed_key(legacy_path)

    km = KeyManager(str(keys_dir), "job-signing")
    km.create(1, write_key_file=_seed_key)
    km.activate(1)
    km.create(2, write_key_file=_seed_key)
    km.activate(2)  # v1 demotes to VERIFY_ONLY
    km.create(3, write_key_file=_seed_key)
    km.activate(3)
    km.retire(1)  # v1 now RETIRED — must never be served

    provider = get_provider({"provider": "file", "file": {"key_path": str(legacy_path)}})
    provider.use_versioned_dir(str(keys_dir))
    signer = JobSigner(provider=provider, keys_dir=str(keys_dir))

    keys = signer.public_keys()
    assert set(keys) == {"2", "3"}
    assert keys["3"] == signer.public_key_b64(version=3)
    assert keys["2"] != keys["3"]


# ── GET /api/v1/agent/signing-keys — HTTP level ─────────────────────────────


@pytest.fixture()
def reset_signer(monkeypatch):
    monkeypatch.delenv("JOB_SIGNING_ENVELOPES", raising=False)
    monkeypatch.delenv("LOKILINUX_KEYS_DIR", raising=False)
    monkeypatch.setattr(job_envelope, "_signer_instance", None)
    monkeypatch.setattr(job_envelope, "_signer_init_done", False)


@pytest.mark.asyncio
async def test_signing_keys_endpoint_versioned(
    client: AsyncClient, tmp_path, monkeypatch, reset_signer
):
    key_path = tmp_path / "job_signing.key"
    _seed_key(key_path)
    keys_dir = tmp_path / "keys"
    monkeypatch.setenv("JOB_SIGNING_KEY_PATH", str(key_path))
    monkeypatch.setenv("LOKILINUX_KEYS_DIR", str(keys_dir))

    resp = await client.get("/api/v1/agent/signing-keys")
    assert resp.status_code == 200
    body = resp.json()
    assert "1" in body
    assert len(base64.b64decode(body["1"])) == 32

    KeyManager(str(keys_dir), "job-signing").rotate(write_key_file=_seed_key)
    monkeypatch.setattr(job_envelope, "_signer_instance", None)
    monkeypatch.setattr(job_envelope, "_signer_init_done", False)

    resp2 = await client.get("/api/v1/agent/signing-keys")
    assert resp2.status_code == 200
    body2 = resp2.json()
    assert set(body2) == {"1", "2"}
    assert body2["1"] == body["1"]  # old version stays VERIFY_ONLY, unchanged


@pytest.mark.asyncio
async def test_signing_keys_endpoint_falls_back_to_legacy(
    client: AsyncClient, tmp_path, monkeypatch, reset_signer
):
    # No usable private key => _get_signer() returns None => falls back to
    # the same JOB_SIGNING_PUB_PATH file /signing-key already serves.
    monkeypatch.setenv("JOB_SIGNING_KEY_PATH", "/nonexistent/private.key")
    pub_path = tmp_path / "job_signing.pub"
    pub_path.write_bytes(
        Ed25519PrivateKey.generate()
        .public_key()
        .public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    )
    monkeypatch.setenv("JOB_SIGNING_PUB_PATH", str(pub_path))

    resp = await client.get("/api/v1/agent/signing-keys")
    assert resp.status_code == 200
    assert set(resp.json()) == {"1"}


@pytest.mark.asyncio
async def test_signing_keys_endpoint_503_without_any_key(
    client: AsyncClient, monkeypatch, reset_signer
):
    monkeypatch.setenv("JOB_SIGNING_KEY_PATH", "/nonexistent/private.key")
    monkeypatch.setenv("JOB_SIGNING_PUB_PATH", "/nonexistent/public.pub")

    resp = await client.get("/api/v1/agent/signing-keys")
    assert resp.status_code == 503
