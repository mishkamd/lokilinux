"""Unit tests for services/approval_claims.py — binding + negative matrix."""

import base64
import time

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from lokilinux.services.approval_claims import (
    ClaimRejected,
    compute_job_hash,
    create_claim,
    verify_claim,
)

PUB = Ed25519PrivateKey.generate()
PRIV = PUB  # same object signs; verify uses .public_key()
NOW = 1780000000
PAYLOAD = {"service_name": "nginx", "action": "restart"}
CAPS = ["SERVICE_CONTROL"]


def make_claim(**overrides):
    kw = dict(
        job_id="job-1", target_agent_id="agent-1", payload=PAYLOAD,
        capabilities=CAPS, approver_id="admin@x", key_version=1,
        ttl_seconds=300, now=NOW,
    )
    kw.update(overrides)
    return create_claim(PRIV, **kw)


def verify_ok(claim, payload=None, target="agent-1", caps=None):
    verify_claim(
        PRIV.public_key(), claim,
        expected_job_id=claim["job_id"],
        expected_payload=payload if payload is not None else PAYLOAD,
        expected_target_agent_id=target,
        required_capabilities=caps or CAPS,
        now=NOW + 10,
    )


def test_valid_claim_verifies():
    verify_ok(make_claim())


def test_job_hash_stable_and_bound():
    c = make_claim()
    assert c["job_hash"] == compute_job_hash(PAYLOAD)
    with pytest.raises(ClaimRejected) as e:
        verify_ok(c, payload={"service_name": "sshd"})
    assert e.value.reason == "modified"


def test_expired_rejected():
    c = make_claim(ttl_seconds=10)
    with pytest.raises(ClaimRejected) as e:
        verify_claim(
            PRIV.public_key(), c, expected_job_id="job-1",
            expected_payload=PAYLOAD, expected_target_agent_id="agent-1",
            required_capabilities=CAPS, now=NOW + 11,
        )
    assert e.value.reason == "expired"


def test_wrong_job_and_wrong_target():
    c = make_claim()
    with pytest.raises(ClaimRejected) as e:
        verify_claim(
            PRIV.public_key(), c, expected_job_id="OTHER",
            expected_payload=PAYLOAD, expected_target_agent_id="agent-1",
            required_capabilities=CAPS, now=NOW + 10,
        )
    assert e.value.reason == "wrong_job"

    c2 = make_claim()
    with pytest.raises(ClaimRejected) as e2:
        verify_ok(c2, target="agent-OTHER")
    assert e2.value.reason == "wrong_target"


def test_missing_capabilities_rejected():
    c = make_claim(capabilities=["READ_SYSTEM"])
    with pytest.raises(ClaimRejected) as e:
        verify_ok(c)
    assert e.value.reason.startswith("missing_capabilities")


def test_modified_signature_rejected():
    c = make_claim()
    c["approver_id"] = "someone-else"
    with pytest.raises(ClaimRejected) as e:
        verify_ok(c)
    assert e.value.reason == "bad_signature"


def test_wrong_key_signature_rejected():
    other = Ed25519PrivateKey.generate()
    c = make_claim()
    # re-sign content with wrong key by rebuilding signature field manually
    from lokilinux.services.approval_claims import canonical_bytes
    unsigned = {k: v for k, v in c.items() if k != "signature"}
    unsigned["signature"] = ""
    c["signature"] = base64.b64encode(other.sign(canonical_bytes(unsigned))).decode()
    with pytest.raises(ClaimRejected) as e:
        verify_ok(c)
    assert e.value.reason == "bad_signature"
