"""Ed25519 job-envelope signing for the LokiLinux control plane.

Trust contract (docs/security/AGENT_SECURITY.md):
  - The private key NEVER leaves this process/host. Agents hold only the
    public half (served at /agent/signing-key).
  - Signatures cover the CANONICAL compact JSON of the envelope without its
    "signature" field, keys sorted — byte-identical to agent/internal/
    security/envelope.go UnsignedBytes(). Numbers inside payloads must be
    integers (float formatting differs across languages).

v2 (plan Faza F): all crypto flows through a SigningProvider (lokilinux.kms).
The legacy single-file layout keeps working as version 1 of the implicit
FileSigningProvider, so existing deployments are untouched.
"""

import base64
import json
import os
import time
import uuid
from typing import Dict, List, Optional

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from lokilinux import metrics
from lokilinux.kms import KeyManager, get_provider
from lokilinux.kms.provider import KeyRef, SigningProvider

DEFAULT_KEY_PATH = "/etc/lokilinux/certs/job_signing.key"


def _load_private_key(key_path: str) -> Ed25519PrivateKey:
    """Legacy loader kept for direct-construction callers/tests."""
    from cryptography.hazmat.primitives import serialization

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
    """Facade over a SigningProvider. Two construction modes:

      JobSigner()                          — legacy: single file => version 1
      JobSigner(provider=..., key_manager=...) — versioned KMS lifecycle
    """

    def __init__(
        self,
        provider: Optional[SigningProvider] = None,
        key_id: str = "job-signing",
        keys_dir: Optional[str] = None,
    ):
        if provider is None:
            provider = get_provider({"provider": "file",
                                     "file": {"key_path": os.environ.get(
                                         "JOB_SIGNING_KEY_PATH", DEFAULT_KEY_PATH)}})
            self._key_manager: Optional[KeyManager] = None
        else:
            self._key_manager = KeyManager(keys_dir or os.environ.get(
                "LOKILINUX_KEYS_DIR", "/var/lib/lokilinux/keys"), key_id)
        self._provider = provider
        self._key_id = key_id

    # ── key resolution ────────────────────────────────────────────────────────
    def _active_ref(self) -> KeyRef:
        if self._key_manager is not None:
            return self._key_manager.active_ref()
        return KeyRef(self._key_id, 1)

    def _ref_for_version(self, version: Optional[int]) -> KeyRef:
        if version is None:
            return self._active_ref()
        if self._key_manager is not None:
            self._key_manager.enforce_verify_allowed(version)
            return KeyRef(self._key_id, version)
        return KeyRef(self._key_id, version)  # legacy layout: only v1 exists

    def public_key_b64(self, version: Optional[int] = None) -> str:
        from cryptography.hazmat.primitives import serialization

        ref = self._ref_for_version(version)
        raw = self._provider.public_key(ref).public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        return base64.b64encode(raw).decode()

    def public_keys(self) -> Dict[str, str]:
        """Version -> base64(raw32 pub) for every publicly-servable version
        (ACTIVE + VERIFY_ONLY; RETIRED never exposed — a retired key must
        stop being trusted by anyone still holding it, not just by new
        verifiers). Legacy (unversioned) layout has exactly one entry, "1".
        Backs GET /agent/signing-keys."""
        if self._key_manager is None:
            return {"1": self.public_key_b64()}
        out: Dict[str, str] = {}
        for v, state in self._key_manager.versions().items():
            if state not in ("ACTIVE", "VERIFY_ONLY"):
                continue
            out[v] = self.public_key_b64(version=int(v))
        return out

    def verify_allowed_version(self, version: int) -> bool:
        if self._key_manager is None:
            return version == 1
        try:
            self._key_manager.enforce_verify_allowed(version)
            return True
        except Exception:
            return False

    def _provider_sign(self, ref: KeyRef, message: bytes) -> bytes:
        """Wraps every provider call with the kms_* metrics (plan §19) — the
        single choke point sign()/sign_message()/sign_approval_claim() share."""
        t0 = time.monotonic()
        try:
            sig = self._provider.sign_message(ref, message)
        except Exception as exc:
            reason = getattr(exc, "reason", None) or exc.__class__.__name__
            metrics.kms_sign_failure_total.labels(reason=reason).inc()
            raise
        finally:
            metrics.kms_provider_latency.observe(time.monotonic() - t0)
        metrics.kms_sign_success_total.inc()
        return sig

    def sign_message(self, message: bytes) -> bytes:
        return self._provider_sign(self._active_ref(), message)

    # ── envelope signing ──────────────────────────────────────────────────────
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
        active = self._active_ref()
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
        if active.version != 1:
            # Contract: key_version is present ONLY when != 1 — matches the Go
            # pointer+omitempty field so canonical bytes stay aligned, and v1
            # envelopes remain byte-identical to pre-KMS releases.
            env["key_version"] = active.version
        env["signature"] = base64.b64encode(self._provider_sign(active, _canonical_unsigned(env))).decode()
        return env

    def sign_approval_claim(self, *, job_id: str, target_agent_id: str,
                            payload: dict, capabilities: List[str],
                            approver_id: str, ttl_seconds: int = 300):
        from lokilinux.services.approval_claims import create_claim

        return create_claim(
            lambda msg: self._provider_sign(self._active_ref(), msg),
            job_id=job_id,
            target_agent_id=target_agent_id,
            payload=payload,
            capabilities=capabilities,
            approver_id=approver_id,
            ttl_seconds=ttl_seconds,
        )


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
