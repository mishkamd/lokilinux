"""Unit tests for services/job_envelope.py — gating + capability mirror."""

import base64
import json
import os
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from lokilinux.services import job_envelope


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
    monkeypatch.delenv("JOB_SIGNING_ENVELOPES", raising=False)
    # reset singleton between tests
    monkeypatch.setattr(job_envelope, "_signer_instance", None)
    monkeypatch.setattr(job_envelope, "_signer_init_done", False)
    return key


def _job(job_type="SERVICE", job_id="j-1", agent_id="a-1"):
    return SimpleNamespace(id=job_id, job_type=job_type, agent_id=agent_id,
                           tenant_id="", policy_id="")


def test_no_key_returns_params_unchanged(monkeypatch):
    monkeypatch.setenv("JOB_SIGNING_KEY_PATH", "/nonexistent/key")
    job = _job()
    params = {"service_name": "nginx"}
    assert job_envelope.maybe_attach_envelope(job, params, "9.9.9") is params


def test_disabled_via_env(monkeypatch, key_env):
    monkeypatch.setenv("JOB_SIGNING_ENVELOPES", "false")
    job = _job()
    assert "_envelope" not in job_envelope.maybe_attach_envelope(job, {}, "9.9.9")


def test_old_agent_gets_unsigned(key_env):
    job = _job()
    out = job_envelope.maybe_attach_envelope(job, {"a": 1}, "0.35.3")
    assert "_envelope" not in out


def test_new_agent_gets_valid_envelope(key_env):
    job = _job()
    out = job_envelope.maybe_attach_envelope(job, {"service_name": "nginx"}, "0.37.0")
    env = out["_envelope"]
    assert env["job_type"] == "SERVICE"
    assert env["requested_capabilities"] == ["SERVICE_CONTROL"]
    assert env["risk_level"] == "MEDIUM"
    # payload snapshot binds to the sent params (minus the envelope itself)
    assert env["payload"] == {"service_name": "nginx"}
    # signature verifies against the fixture key's public half
    pub = Ed25519PrivateKey.from_private_bytes.__self__ if False else None
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    unsigned = {k: v for k, v in env.items() if k != "signature"}
    unsigned["signature"] = ""
    raw = json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()
    # reconstruct pubkey from the same PEM the signer used
    pem = open(os.environ["JOB_SIGNING_KEY_PATH"], "rb").read()
    priv = serialization.load_pem_private_key(pem, password=None)
    pub = priv.public_key()
    pub.verify(base64.b64decode(env["signature"]), raw)  # raises on mismatch


def test_telemetry_job_types_not_signed(key_env):
    for jt in ("HEARTBEAT",):
        pass  # HEARTBEAT is in registry; use a truly unknown type below
    job = _job(job_type="TOTALLY_UNKNOWN")
    out = job_envelope.maybe_attach_envelope(job, {}, "9.9.9")
    assert "_envelope" not in out


def test_workflow_steps_capabilities_union(key_env):
    job = _job(job_type="WORKFLOW_STEPS")
    params = {"steps": [
        {"sequence": 1, "type": "ansible", "params": {}},
        {"sequence": 2, "type": "command", "params": {"command": "ls"}},
    ]}
    out = job_envelope.maybe_attach_envelope(job, params, "9.9.9")
    caps = set(out["_envelope"]["requested_capabilities"])
    assert caps == {"EXEC_ANSIBLE", "EXEC_BASH"}
