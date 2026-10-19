"""
LokiLinux — Agent policy compile, validate, sign.

Policy documents arrive as YAML (admin editor) and are stored as JSONB
payloads. This module owns the strict pipeline between the two:

    parse (yaml→dict) → validate (schema, deny-by-default) → canonical bytes
    → sha256 hash → ed25519 signature

Principles from the plan (docs/superpowers/plans/2026-08-23-agent-policy-modernization-plan.md):
  - unknown fields REJECTED (not warned)
  - numeric intervals clamped to schema bounds
  - max payload 1 MB
  - canonical form = sorted-keys compact JSON (same recipe as job envelopes)

Signing uses a dedicated ed25519 keypair (separate from the TLS CA and from
job signing): file-based at POLICY_SIGNING_KEY_PATH, generated on first use.
"""

import base64
import hashlib
import json
import logging
import os
from typing import Any

import yaml as pyyaml

logger = logging.getLogger(__name__)

ALLOWED_API_VERSIONS = {"lokilinux.io/v1"}
MAX_PAYLOAD_BYTES = 1024 * 1024

HEARTBEAT_INTERVAL_BOUNDS = (10, 300)
HEALTH_INTERVAL_BOUNDS = (10, 3600)

KNOWN_COLLECTORS = {
    "auditd", "sshd", "users", "packages", "services", "network", "sysctl",
    "processes", "time_sync", "file_integrity", "kernel", "cron", "docker",
    "mounts", "updates", "certificates", "dns", " firewall".strip(),
}


class PolicyValidationError(ValueError):
    """Raised for any payload the agent would (or must) refuse."""


def canonical_bytes(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


def payload_hash(payload: dict) -> str:
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()


# ── parse ─────────────────────────────────────────────────────────────────────

def parse_yaml(text: str) -> dict:
    if not text or not text.strip():
        raise PolicyValidationError("empty document")
    if len(text.encode()) > MAX_PAYLOAD_BYTES:
        raise PolicyValidationError(f"payload exceeds {MAX_PAYLOAD_BYTES} bytes")
    try:
        doc = pyyaml.safe_load(text)
    except pyyaml.YAMLError as exc:
        raise PolicyValidationError(f"invalid YAML: {exc}") from exc
    if not isinstance(doc, dict):
        raise PolicyValidationError("document must be a mapping")
    return doc


# ── validate ──────────────────────────────────────────────────────────────────

def _reject_unknown(mapping: dict, allowed: set, where: str) -> None:
    unknown = set(mapping) - allowed
    if unknown:
        raise PolicyValidationError(f"{where}: unknown field(s): {sorted(unknown)}")


def _clamp_int(value: Any, bounds: tuple[int, int], where: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise PolicyValidationError(f"{where}: must be an integer")
    lo, hi = bounds
    return max(lo, min(hi, value))


def validate(doc: dict) -> dict:
    """Validate + normalize in place. Returns the normalized dict; raises
    PolicyValidationError on any violation. Unknown top-level sections
    (signals/services/logs/limits/buffer/compliance/otel) are accepted but
    MUST be empty mappings in MVP — they activate in Faza 5."""
    api_version = doc.get("apiVersion")
    if api_version not in ALLOWED_API_VERSIONS:
        raise PolicyValidationError(
            f"apiVersion: unsupported {api_version!r}, expected one of {sorted(ALLOWED_API_VERSIONS)}"
        )
    if doc.get("kind") != "AgentPolicy":
        raise PolicyValidationError("kind: must be 'AgentPolicy'")

    metadata = doc.get("metadata")
    if not isinstance(metadata, dict) or not str(metadata.get("name", "")).strip():
        raise PolicyValidationError("metadata.name: required non-empty string")

    spec = doc.get("spec")
    if spec is None:
        spec = {}
    if not isinstance(spec, dict):
        raise PolicyValidationError("spec: must be a mapping")

    _reject_unknown(spec, {"collectors", "heartbeat", "health", "signals", "services",
                           "logs", "limits", "buffer", "compliance", "otel"}, "spec")

    collectors = spec.get("collectors")
    if collectors is None:
        collectors = {}
    if not isinstance(collectors, dict):
        raise PolicyValidationError("spec.collectors: must be a mapping of collector name -> config")
    for name, cfg in collectors.items():
        if name not in KNOWN_COLLECTORS:
            raise PolicyValidationError(f"spec.collectors: unknown collector {name!r}")
        if not isinstance(cfg, dict):
            raise PolicyValidationError(f"spec.collectors.{name}: must be a mapping")
        enabled = cfg.get("enabled", True)
        if not isinstance(enabled, bool):
            raise PolicyValidationError(f"spec.collectors.{name}.enabled: must be boolean")
        _reject_unknown(cfg, {"enabled"}, f"spec.collectors.{name}")
    # deny-by-default normalization: every known-but-unlisted collector is disabled
    spec["collectors"] = {**{c: {"enabled": False} for c in sorted(KNOWN_COLLECTORS - set(collectors))},
                          **collectors}

    heartbeat = spec.get("heartbeat") or {}
    if not isinstance(heartbeat, dict):
        raise PolicyValidationError("spec.heartbeat: must be a mapping")
    _reject_unknown(heartbeat, {"interval_seconds"}, "spec.heartbeat")
    if "interval_seconds" in heartbeat or True:
        heartbeat["interval_seconds"] = _clamp_int(
            heartbeat.get("interval_seconds", 60), HEARTBEAT_INTERVAL_BOUNDS, "spec.heartbeat.interval_seconds"
        )
    spec["heartbeat"] = heartbeat

    health = spec.get("health") or {}
    if not isinstance(health, dict):
        raise PolicyValidationError("spec.health: must be a mapping")
    _reject_unknown(health, {"collect_interval_seconds"}, "spec.health")
    health["collect_interval_seconds"] = _clamp_int(
        health.get("collect_interval_seconds", 30), HEALTH_INTERVAL_BOUNDS, "spec.health.collect_interval_seconds"
    )
    spec["health"] = health

    for reserved in ("signals", "services", "logs", "limits", "buffer", "compliance", "otel"):
        section = spec.get(reserved)
        if section in (None, {}):
            if reserved in spec:
                del spec[reserved]
            continue
        if isinstance(section, dict) and any(section.values()):
            raise PolicyValidationError(
                f"spec.{reserved}: runtime enforcement lands in Faza 5 — accept empty mapping only"
            )

    doc["spec"] = spec
    return doc


# ── signing ───────────────────────────────────────────────────────────────────

_POLICY_KEY_ENV = "POLICY_SIGNING_KEY_PATH"
_DEFAULT_POLICY_KEY = "/var/lib/lokilinux/policy-signing.key"


def _load_or_create_private_key():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    path = os.environ.get(_POLICY_KEY_ENV, _DEFAULT_POLICY_KEY)
    if os.path.exists(path):
        with open(path, "rb") as fh:
            return serialization.load_pem_private_key(fh.read(), password=None)
    key = Ed25519PrivateKey.generate()
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(pem)
    logger.info("generated policy signing key at %s", path)
    return key


def public_key_b64() -> str:
    """base64(raw ed25519 public key) — served to agents for pinning."""
    from cryptography.hazmat.primitives import serialization

    key = _load_or_create_private_key()
    raw = key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return base64.b64encode(raw).decode()


def sign_payload(payload: dict) -> str:
    """base64 ed25519 signature over the canonical payload bytes."""
    key = _load_or_create_private_key()
    sig = key.sign(canonical_bytes(payload))
    return base64.b64encode(sig).decode()


def verify_signature(payload: dict, signature_b64: str, public_key_b64_str: str) -> bool:
    """Mirror of the agent-side check — used by tests and by the admin UI's
    verify button."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    try:
        raw = base64.b64decode(public_key_b64_str)
        pub = Ed25519PublicKey.from_public_bytes(raw)
        pub.verify(base64.b64decode(signature_b64), canonical_bytes(payload))
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False
