"""Prometheus metrics for security-relevant control-plane events (plan §19).

Exposed via prometheus_client's HTTP server on METRICS_PORT (compose already
publishes 9090). Counters only ever carry labels like outcome/reason — never
serials, agent payloads or key material.
"""

from prometheus_client import Counter, Histogram, start_http_server

# ── Signed jobs (§4) ──────────────────────────────────────────────────────────
unsigned_privileged_jobs_total = Counter(
    "unsigned_privileged_jobs_total",
    "Privileged jobs dispatched WITHOUT an envelope (version-gated or signing unavailable)",
)
signed_jobs_total = Counter("signed_jobs_total", "Jobs dispatched with a signed envelope")
invalid_signature_total = Counter(
    "invalid_signature_total", "Agent-rejected jobs: bad signature", ["reason"]
)
expired_signature_total = Counter("expired_signature_total", "Agent-rejected jobs: expired envelope")
unknown_signer_total = Counter("unknown_signer_total", "Signatures not verifiable with any known key version")
replayed_job_total = Counter("replayed_job_total", "Replayed jobs rejected agent-side")
agent_rejected_jobs_total = Counter(
    "agent_rejected_jobs_total", "Jobs rejected by the agent pre-dispatch gate", ["code"]
)
revoked_agent_total = Counter("revoked_agent_total", "Connections rejected for revoked certificate/identity")
certificate_rejected_total = Counter(
    "certificate_rejected_total", "mTLS connections rejected by revocation checks", ["outcome"]
)

# ── KMS (§19) ────────────────────────────────────────────────────────────────
kms_sign_success_total = Counter("kms_sign_success_total", "Successful KMS sign operations")
kms_sign_failure_total = Counter("kms_sign_failure_total", "Failed KMS sign operations", ["reason"])
kms_provider_latency = Histogram(
    "kms_provider_latency_seconds", "SigningProvider call latency",
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0),
)
kms_rotation_total = Counter("kms_rotation_total", "Key rotations performed")

# ── Approvals (§19) ──────────────────────────────────────────────────────────
approval_claims_issued_total = Counter(
    "approval_claims_issued_total", "Approval claims issued"
)
approval_rejected_total = Counter(
    "approval_rejected_total", "Approval claim verification failures", ["reason"]
)

# ── Exec broker (§19) ────────────────────────────────────────────────────────
exec_broker_requests_total = Counter(
    "exec_broker_requests_total", "Exec broker operations executed", ["operation"]
)
exec_broker_denied_total = Counter(
    "exec_broker_denied_total", "Exec broker requests denied", ["reason"]
)


def start_metrics_server(port: int) -> None:
    """Starts the prometheus_client HTTP server (idempotent per process)."""
    try:
        start_http_server(port)
    except OSError:
        # Port already bound (e.g. api+grpc share the image) — first binder wins,
        # second process logs and continues without its own exporter.
        import logging

        logging.getLogger(__name__).warning(
            "metrics port %d busy — metrics served by another process in this image", port
        )
