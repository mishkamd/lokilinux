"""Ed25519 job-envelope signing for the LokiLinux control plane.

Trust contract (docs/security/AGENT_SECURITY.md):
  - The private key NEVER leaves this process/host (JOB_SIGNING_KEY_PATH,
    0600). Agents hold only the public half via GET /agent/signing-key.
  - Signatures cover the CANONICAL compact JSON of the envelope without its
    "signature" field, keys sorted — byte-identical to agent/internal/
    security/envelope.go UnsignedBytes(). Numbers inside payloads must be
    integers (float formatting differs across languages).
"""

import base64
import json
import os
import time
import uuid
from typing import List, Optional

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

DEFAULT_KEY_PATH = "/etc/lokilinux/certs/job_signing.key"


def _load_private_key(key_path: str) -> Ed25519PrivateKey:
    with open(key_path, "rb") as f:
        raw = f.read()
    if len(raw) == 32:
        return Ed25519PrivateKey.from_private_bytes(raw)
    key = serialization.load_pem_private_key(raw, password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError(f"{key_path}: not an Ed25519 private key")
    return key


def _canonical_unsigned(env: dict) -> bytes:
    """Canonical bytes signatures cover: every field present, signature
    empty string, sorted keys, compact separators. Mirrors envelope.go."""
    unsigned = {k: v for k, v in env.items() if k != "signature"}
    unsigned["signature"] = ""
    return json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()


class JobSigner:
    def __init__(self, key_path: Optional[str] = None):
        self._key = _load_private_key(key_path or os.environ.get("JOB_SIGNING_KEY_PATH", DEFAULT_KEY_PATH))

    def public_key_b64(self) -> str:
        """base64(raw 32-byte public) — the exact format agents consume."""
        raw = self._key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        return base64.b64encode(raw).decode()

    def sign(
        self,
        job_id: str,
        agent_id: str,
        tenant_id: str,
        job_type: str,
        payload: dict,
        policy_id: str = "",
        ttl_seconds: int = 300,
        risk_level: str = "HIGH",
        requested_capabilities: Optional[List[str]] = None,
        now: Optional[int] = None,
    ) -> dict:
        """Returns the full signed envelope dict, ready to embed under the
        "_envelope" key of a job's parameters."""
        ts = int(now) if now is not None else int(time.time())
        env = {
            "job_id": job_id,
            "agent_id": agent_id,
            "tenant_id": tenant_id or "",
            "job_type": job_type,
            "payload": payload if payload is not None else {},
            "policy_id": policy_id or "",
            "issued_at": ts,
            "expires_at": ts + ttl_seconds,
            "nonce": uuid.uuid4().hex,
            "risk_level": risk_level or "",
            "requested_capabilities": list(requested_capabilities or []),
            "signature": "",
        }
        env["signature"] = base64.b64encode(self._key.sign(_canonical_unsigned(env))).decode()
        return env


def verify_fixture(pub_b64: str, env: dict) -> bool:
    """Control-plane-side self-check of a signed envelope (tests only —
    the authoritative verification lives agent-side in Go)."""
    from cryptography.exceptions import InvalidSignature

    pub = Ed25519PublicKey.from_public_bytes(base64.b64decode(pub_b64))
    try:
        pub.verify(base64.b64decode(env["signature"]), _canonical_unsigned(env))
        return True
    except InvalidSignature:
        return False
