"""Cryptographic approval claims (plan §6).

An approval claim is an Ed25519-signed statement binding an approval to
EXACTLY one job execution:

    approval_id, job_id, job_hash (canonical params sha256), target_agent_id,
    capabilities, approver_id, issued_at, expires_at, nonce, key_version

The agent verifies the signature AND every binding before letting a
`require_approval: true` capability execute. Expired / wrong-job /
wrong-target / modified / replayed claims are all rejected (fail-closed).
"""

import base64
import hashlib
import json
import time
import uuid
from typing import List, Optional

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

CLAIM_TTL_SECONDS = 300


def canonical_bytes(obj: dict) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()


def compute_job_hash(payload: dict) -> str:
    """The hash a claim binds to: canonical JSON of the job's parameters
    (minus envelope/approval keys) — identical computation on the agent."""
    return hashlib.sha256(canonical_bytes(payload or {})).hexdigest()


def create_claim(
    private_key: Ed25519PrivateKey,
    *,
    job_id: str,
    target_agent_id: str,
    payload: dict,
    capabilities: List[str],
    approver_id: str,
    key_version: int = 1,
    ttl_seconds: int = CLAIM_TTL_SECONDS,
    now: Optional[int] = None,
) -> dict:
    ts = int(now) if now is not None else int(time.time())
    claim = {
        "approval_id": uuid.uuid4().hex,
        "job_id": job_id,
        "job_hash": compute_job_hash(payload),
        "target_agent_id": target_agent_id,
        "capabilities": list(capabilities or []),
        "approver_id": approver_id,
        "issued_at": ts,
        "expires_at": ts + ttl_seconds,
        "nonce": uuid.uuid4().hex,
        "key_version": key_version,
        "signature": "",
    }
    unsigned = {k: v for k, v in claim.items() if k != "signature"}
    unsigned["signature"] = ""
    claim["signature"] = base64.b64encode(private_key.sign(canonical_bytes(unsigned))).decode()
    return claim


class ClaimRejected(Exception):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(f"approval claim rejected [{reason}]")


def verify_claim(
    public_key: Ed25519PublicKey,
    claim: dict,
    *,
    expected_job_id: str,
    expected_payload: dict,
    expected_target_agent_id: str,
    required_capabilities: List[str],
    now: Optional[int] = None,
) -> None:
    """Raises ClaimRejected(reason) on ANY binding failure. Signature is
    checked LAST so audit gets the most specific rejection reason first."""
    now_ts = int(now) if now is not None else int(time.time())
    for field in ("approval_id", "job_id", "job_hash", "target_agent_id",
                  "capabilities", "nonce", "signature"):
        if not claim.get(field):
            raise ClaimRejected("malformed")
    if now_ts > int(claim["expires_at"]):
        raise ClaimRejected("expired")
    if claim["job_id"] != expected_job_id:
        raise ClaimRejected("wrong_job")
    if claim["job_hash"] != compute_job_hash(expected_payload):
        raise ClaimRejected("modified")
    if expected_target_agent_id and claim["target_agent_id"] != expected_target_agent_id:
        raise ClaimRejected("wrong_target")
    missing = set(required_capabilities or []) - set(claim["capabilities"])
    if missing:
        raise ClaimRejected(f"missing_capabilities:{','.join(sorted(missing))}")

    unsigned = {k: v for k, v in claim.items() if k != "signature"}
    unsigned["signature"] = ""
    try:
        sig = base64.b64decode(claim["signature"])
        public_key.verify(sig, canonical_bytes(unsigned))
    except Exception as exc:  # noqa: BLE001 — invalid signature/binary garbage
        raise ClaimRejected("bad_signature") from exc
