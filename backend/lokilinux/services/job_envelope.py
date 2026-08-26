"""Signed-job envelopes: control-plane half of the agent trust model.

maybe_attach_envelope() decides, per (job, agent), whether a privileged job
gets an Ed25519-signed "_envelope" embedded in its parameters:

  - only when a signing key is provisioned and envelopes are enabled
  - only for PRIVILEGED job types (the capability registry below mirrors
    agent/internal/security/capabilities.go 1:1)
  - only for agents whose version understands the pipeline
    (MIN_AGENT_VERSION_SIGNED_JOBS in utils/agent_capability.py)

The envelope's payload is a snapshot of the exact parameters being sent, so
agent-side verification binds the signature to what will execute.
"""

import base64
import json
import logging
import os
from typing import List, Optional

from lokilinux.utils.agent_capability import (
    MIN_AGENT_VERSION_SIGNED_JOBS,
    agent_meets_minimum,
)
from lokilinux import metrics
from lokilinux.kms import KeyManager, get_provider
from lokilinux.services.job_signing import JobSigner

logger = logging.getLogger(__name__)

# job_type -> (capability, risk). MUST stay in sync with the Go registry.
_CAPABILITY_REGISTRY = {
    "HEARTBEAT": ("READ_SYSTEM", "LOW"),
    "FILE_READ": ("READ_SYSTEM", "LOW"),
    "LOG_READ": ("READ_LOGS", "LOW"),
    "SERVICE": ("SERVICE_CONTROL", "MEDIUM"),
    "FILE": ("FILE_WRITE", "MEDIUM"),
    "PACKAGE_UPDATE": ("PACKAGE_MANAGEMENT", "HIGH"),
    "COMPLIANCE_REMEDIATE": ("SECURITY_REMEDIATION", "HIGH"),
    "FIREWALL_CHANGE": ("FIREWALL_CONFIGURATION", "HIGH"),
    "REBOOT": ("REBOOT_HOST", "HIGH"),
    "WORKFLOW_STEPS": ("EXEC_BASH", "CRITICAL"),
    "CUSTOM_COMMAND": ("EXEC_BASH", "CRITICAL"),
    "ANSIBLE_PLAYBOOK": ("EXEC_ANSIBLE", "CRITICAL"),
    "PLUGIN_INSTALL": ("PLUGIN_INSTALL", "CRITICAL"),
}

_STEP_TYPE_TO_CAP = {
    "command": "EXEC_BASH",
    "package": "PACKAGE_MANAGEMENT",
    "service": "SERVICE_CONTROL",
    "system": "REBOOT_HOST",
    "file": "FILE_WRITE",
    "ansible": "EXEC_ANSIBLE",
}

_signer_instance: Optional[JobSigner] = None
_signer_init_done = False


def _required_capabilities(job_type: str, params: dict) -> List[str]:
    if job_type == "WORKFLOW_STEPS":
        caps = []
        for step in params.get("steps") or []:
            st = step.get("type") if isinstance(step, dict) else None
            cap = _STEP_TYPE_TO_CAP.get(st or "")
            if cap and cap not in caps:
                caps.append(cap)
        return caps or ["EXEC_BASH"]
    cap = _CAPABILITY_REGISTRY.get(job_type)
    return [cap[0]] if cap else []


def _risk_level(job_type: str) -> str:
    return (_CAPABILITY_REGISTRY.get(job_type) or ("", "HIGH"))[1]


def signing_required() -> bool:
    """True when the deployment demands signed dispatch — envelopes MUST be
    attachable; an unusable signer then fails closed instead of silently
    downgrading to unsigned privileged execution."""
    return os.environ.get("JOB_SIGNING_REQUIRED", "").lower() in ("1", "true", "yes")


def _bootstrap_versioned_key(key_manager: KeyManager, legacy_key_path: str) -> None:
    """First activation of the versioned layout: seeds v1 from the existing
    legacy key file's bytes so rotation has a known starting point, without
    touching the legacy file agents/installers already trust. No-op once any
    version is registered (rotation has already taken over)."""
    if key_manager.active_version() is not None or key_manager.state_of(1) is not None:
        return
    with open(legacy_key_path, "rb") as f:
        raw = f.read()

    def _write(path: str) -> None:
        with open(path, "wb") as out:
            out.write(raw)

    key_manager.create(1, write_key_file=_write)
    key_manager.activate(1)


def _get_signer() -> Optional[JobSigner]:
    """Lazily construct the singleton signer. Returns None while no usable
    key is provisioned; a later call re-attempts (cheap file stat).
    Raises when job_signing_required=True and the key never materializes —
    no-downgrade guarantee (plan C3).

    When LOKILINUX_KEYS_DIR is set, this wires JobSigner to the versioned
    KeyManager lifecycle (bootstrapping v1 from the legacy file on first use)
    so admin-triggered rotation actually reaches the running dispatch path —
    without it, KeyManager.rotate() would mutate state nothing ever reads."""
    global _signer_instance, _signer_init_done
    key_path = os.environ.get("JOB_SIGNING_KEY_PATH", "/etc/lokilinux/certs/job_signing.key")
    keys_dir = os.environ.get("LOKILINUX_KEYS_DIR", "")
    enabled = os.environ.get("JOB_SIGNING_ENVELOPES", "true").lower() != "false"
    if not enabled:
        if signing_required():
            raise RuntimeError(
                "job_signing_required=true but JOB_SIGNING_ENVELOPES disabled — refusing unsigned dispatch"
            )
        return None
    if not os.path.isfile(key_path):
        if signing_required():
            raise RuntimeError(
                f"job_signing_required=true but signing key missing at {key_path} — refusing unsigned dispatch"
            )
        return None
    if not _signer_init_done:
        try:
            if keys_dir:
                provider = get_provider({"provider": os.environ.get("KMS_PROVIDER", "file"),
                                         "file": {"key_path": key_path}})
                _bootstrap_versioned_key(KeyManager(keys_dir, "job-signing"), key_path)
                _signer_instance = JobSigner(provider=provider, keys_dir=keys_dir)
            else:
                _signer_instance = JobSigner()  # legacy layout: implicit v1 only
        except Exception:  # noqa: BLE001 — unusable key must never break dispatch
            logger.exception("job signing key unreadable — envelopes disabled")
        _signer_init_done = True
    return _signer_instance


def maybe_attach_envelope(
    job, params: dict, agent_version: Optional[str], agent_id: Optional[str] = None
) -> dict:
    """Returns params, with an "_envelope" added when this job/agent pair
    qualifies for signed execution. Never raises.

    agent_id: the real recipient — the gRPC dispatch loop passes agent.id here.
    Job has no single agent_id column (multi-target via target_servers), so
    falling back to job.agent_id only covers legacy single-target callers.
    """
    try:
        signer = _get_signer()
        if signer is None:
            metrics.unsigned_privileged_jobs_total.inc()
            return params
        job_type = getattr(job, "job_type", "") or ""
        if job_type not in _CAPABILITY_REGISTRY:
            return params
        if not agent_meets_minimum(agent_version, MIN_AGENT_VERSION_SIGNED_JOBS):
            return params

        payload = {k: v for k, v in (params or {}).items() if k != "_envelope"}
        env = signer.sign(
            job_id=str(getattr(job, "id", "")),
            agent_id=str(agent_id or getattr(job, "agent_id", "") or ""),
            tenant_id=str(getattr(job, "tenant_id", "") or ""),
            job_type=job_type,
            payload=payload,
            policy_id=str(getattr(job, "policy_id", "") or ""),
            risk_level=_risk_level(job_type),
            requested_capabilities=_required_capabilities(job_type, payload),
        )
        out = dict(payload)
        out["_envelope"] = env
        return out
    except Exception:  # noqa: BLE001 — signing failure must never drop a job
        logger.exception("envelope attachment failed — sending unsigned")
        return params


def canonical_payload_bytes(payload: dict) -> bytes:
    """Exposed for tests: the exact bytes covered by the signature inside the
    full-envelope canonical form (sorted keys, compact separators)."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


def pub_b64_len_ok(b64: str) -> bool:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    try:
        Ed25519PublicKey.from_public_bytes(base64.b64decode(b64))
        return True
    except Exception:
        return False
