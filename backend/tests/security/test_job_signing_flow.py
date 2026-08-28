"""Signed-job attack matrix (agent-security-hardening plan P12, §35) — the
backend-observable rows only. Named explicitly in the plan's P12 file list;
this closes that specific gap.

Scope note: `verify_fixture` (job_signing.py) is a pure signature check —
the SAME canonical-bytes verification agent/internal/security/envelope.go's
Verifier.Check runs first, before its own additional checks (expiry,
replay/duplicate-nonce, wrong-agent-id authorization, capability/policy
gating) that only make sense agent-side, against agent-local state
(replay store, local policy cache) the backend doesn't have. Those rows are
already covered by `agent/internal/agent/job_validation_test.go` and
`agent/internal/security/envelope_test.go` (confirmed present). What's
tested here is the actual security property the signature provides at
THIS layer: no single byte of a signed envelope — signature, payload,
agent_id, or the expiry timestamp itself — can be altered post-signing
without invalidating the signature. "unsigned privileged job (flag ON)" is
already covered by test_job_envelope.py's signing_required()/
maybe_attach_envelope tests; "unsigned plugin" by
agent/internal/modules/plugin_signature_test.go — not duplicated here.
"""

import base64
import copy

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from lokilinux.services.job_signing import JobSigner, verify_fixture


@pytest.fixture()
def key_env(tmp_path, monkeypatch):
    key = Ed25519PrivateKey.generate()
    path = tmp_path / "job_signing.key"
    path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    monkeypatch.setenv("JOB_SIGNING_KEY_PATH", str(path))
    return str(path)


@pytest.fixture()
def signer(key_env):
    return JobSigner()


@pytest.fixture()
def signed_envelope(signer):
    return signer.sign(
        job_id="job-1",
        agent_id="agent-1",
        tenant_id="default",
        job_type="SERVICE",
        payload={"action": "restart", "service": "nginx"},
        policy_id="policy-1",
        risk_level="MEDIUM",
        requested_capabilities=["SERVICE_CONTROL"],
        now=1_780_000_000,
    )


def test_valid_envelope_verifies(signer, signed_envelope):
    """Positive case — the matrix's negative rows only mean something
    relative to this passing first."""
    assert verify_fixture(signer.public_key_b64(), signed_envelope) is True


def test_bad_signature_rejected(signer, signed_envelope):
    env = copy.deepcopy(signed_envelope)
    raw = bytearray(base64.b64decode(env["signature"]))
    raw[0] ^= 0xFF  # flip a byte — same length, invalid signature
    env["signature"] = base64.b64encode(bytes(raw)).decode()
    assert verify_fixture(signer.public_key_b64(), env) is False


def test_tampered_payload_rejected(signer, signed_envelope):
    """Modified payload post-signing — the canonical bytes the signature
    covers change, so the old signature no longer verifies."""
    env = copy.deepcopy(signed_envelope)
    env["payload"] = {"action": "restart", "service": "sshd"}  # attacker swaps the target
    assert verify_fixture(signer.public_key_b64(), env) is False


def test_tampered_agent_id_rejected(signer, signed_envelope):
    """Wrong agent_id — a signed job cannot be redirected to a different
    agent by rewriting the envelope's agent_id after signing."""
    env = copy.deepcopy(signed_envelope)
    env["agent_id"] = "agent-2"
    assert verify_fixture(signer.public_key_b64(), env) is False


def test_extended_expiry_rejected(signer, signed_envelope):
    """expires_at is itself inside the signed bytes — an attacker
    replaying an expiring envelope can't extend its life without
    invalidating the signature (actual expiry *enforcement* is
    agent-side, but the field can't be silently stretched either)."""
    env = copy.deepcopy(signed_envelope)
    env["expires_at"] = env["expires_at"] + 3600
    assert verify_fixture(signer.public_key_b64(), env) is False


def test_tampered_risk_level_rejected(signer, signed_envelope):
    """A downgrade attempt (HIGH -> LOW) is just another field tamper."""
    env = copy.deepcopy(signed_envelope)
    env["risk_level"] = "LOW"
    assert verify_fixture(signer.public_key_b64(), env) is False


def test_wrong_signer_key_rejected(signed_envelope):
    """Signature verifies only against the key that actually signed it —
    a different (attacker-controlled) key must never validate."""
    other = Ed25519PrivateKey.generate()
    other_pub_b64 = base64.b64encode(
        other.public_key().public_bytes(
            encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
        )
    ).decode()
    assert verify_fixture(other_pub_b64, signed_envelope) is False


def test_grpc_message_size_ceiling_matches_client_and_server():
    """Oversized job (>16MB) rejected at transport — regression guard on
    the configured ceiling itself (both sides pinned to 16MB, proto file's
    own header comment names this as the contract); a live 16MB+ transfer
    is integration-test territory (scripts/security/e2e_signed_job.sh),
    not something this unit test spins up."""
    import re
    from pathlib import Path

    grpc_server_src = __import__("lokilinux.grpc_server", fromlist=["*"]).__file__
    with open(grpc_server_src) as f:
        server_src = f.read()
    assert "16 * 1024 * 1024" in server_src, "server grpc.max_recv_message_length must stay 16MB"

    repo_root = Path(__file__).resolve().parents[3]
    client_path = repo_root / "agent" / "internal" / "communication" / "grpc_client.go"
    with open(client_path) as f:
        client_src = f.read()
    match = re.search(r"maxMsgSize\s*=\s*(\d+)\s*\*\s*1024\s*\*\s*1024", client_src)
    assert (
        match and int(match.group(1)) == 16
    ), "agent maxMsgSize must stay pinned to 16MB, matching the server"
