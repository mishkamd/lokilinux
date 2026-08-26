"""
LokiLinux — gRPC AgentServicer: bidirectional heartbeat stream.

Inherits from proto-generated AgentServiceServicer once proto/ is compiled.
Until then this is a standalone class wiring AgentService into the gRPC layer.

Heartbeat flow:
  agent → HeartbeatRequest(agent_id, ip_address, system_info)
  server → HeartbeatResponse(pending_jobs, policy_delta)
"""

import logging
import re

import grpc
from cryptography import x509
from cryptography.x509.oid import NameOID

from lokilinux.services.agent_service import AgentService
from lokilinux.services.cert_revocation import (
    CertificateRevoked,
    RevocationUnavailable,
    assert_not_revoked,
)
from lokilinux.events.publish import emit, is_pipeline_enabled
from lokilinux.services.compliance_ingest_service import (
    diff_domain_hashes,
    publish_domain_hashes,
    publish_domain_snapshots,
)
from lokilinux import metrics
from lokilinux.services.job_envelope import maybe_attach_envelope
from lokilinux.services.policy_service import get_job_timeout_seconds

logger = logging.getLogger(__name__)


def _peer_cert_common_name(context) -> str | None:
    """Extract the CN from the mTLS peer certificate. Fail-closed: any parse
    problem or missing cert returns None and the caller rejects the stream.

    Certificates are minted with CN=agent_id at enrollment
    (api/v1/routers/agent_install.py::_generate_agent_cert), so the CN is the
    only trustworthy statement of agent identity on the wire.
    """
    if context is None:
        return None
    try:
        auth_ctx = context.auth_context() or {}
        pems = auth_ctx.get("x509_pem_cert") or []
        if not pems:
            return None
        raw = pems[0]
        pem = raw.encode() if isinstance(raw, str) else bytes(raw)
        cert = x509.load_pem_x509_certificate(pem)
        attrs = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
        return attrs[0].value.strip() if attrs else None
    except Exception:
        logger.warning("gRPC auth: failed to parse peer certificate", exc_info=True)
        return None


def _peer_cert_serial(context):
    """Serial (hex, lowercase) of the verified mTLS client certificate —
    parsed from the handshake cert, NEVER from agent-supplied fields.
    Returns None when absent/unparseable; callers decide policy."""
    if context is None:
        return None
    try:
        auth_ctx = context.auth_context() or {}
        pems = auth_ctx.get("x509_pem_cert") or []
        if not pems:
            return None
        raw = pems[0]
        pem = raw.encode() if isinstance(raw, str) else bytes(raw)
        return format(x509.load_pem_x509_certificate(pem).serial_number, "x")
    except Exception:
        logger.warning("gRPC auth: failed to read certificate serial", exc_info=True)
        return None


def _revoked_key(agent_id: str) -> str:
    return f"agent:revoked:{agent_id}"


async def revoke_agent_identity(cache, agent_id: str) -> None:
    """Deny-list an agent identity — checked on every heartbeat connection.

    Call from deregistration flows; the cert itself remains cryptographically
    valid until expiry (no CRL yet), so this flag is what actually stops it.
    """
    await cache.set_cached(_revoked_key(agent_id), True)  # no TTL = persists


async def unrevoke_agent_identity(cache, agent_id: str) -> None:
    await cache.invalidate(_revoked_key(agent_id))


_REJECT_RE = re.compile(r"rejected \[(\w+)\]")


def _count_agent_rejections(job_results) -> None:
    """Increment security counters from agent-reported job failures. The agent
    encodes its pre-dispatch gate verdicts as `rejected [code]: detail`."""
    if not job_results:
        return
    for r in job_results:
        err = str(getattr(r, "error", None) or "")
        m = _REJECT_RE.search(err)
        if not m:
            continue
        code = m.group(1).lower()
        metrics.agent_rejected_jobs_total.labels(code=code).inc()
        if code == "bad_signature":
            metrics.invalid_signature_total.labels(reason="bad_signature").inc()
        elif code == "expired":
            metrics.expired_signature_total.inc()
        elif code == "duplicate_job":
            metrics.replayed_job_total.inc()


def _needs_recursion(v) -> bool:
    return isinstance(v, list) or hasattr(v, "__dict__") or isinstance(v, dict)


def _as_dict(obj):
    """The JSON codec parses nested objects as SimpleNamespace, not dict —
    recurse so nested lists/objects (e.g. system_status.disks) come out as
    plain JSON-safe dicts/lists too, not left as SimpleNamespace."""
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return {k: _as_dict(v) if _needs_recursion(v) else v for k, v in obj.items()}
    if isinstance(obj, list):
        return [_as_dict(v) if _needs_recursion(v) else v for v in obj]
    return {k: _as_dict(v) if _needs_recursion(v) else v for k, v in vars(obj).items()}

def _parameters_for_agent(job, agent_id) -> dict:
    """Filter job parameters per-agent for COMPLIANCE_REMEDIATE jobs.

    For non-remediation jobs, returns parameters unchanged.
    For COMPLIANCE_REMEDIATE, extracts only this agent's actions from the
    fleet-wide actions map, so the agent never sees other agents' payloads.
    """
    params = job.parameters or {}
    if job.job_type != "COMPLIANCE_REMEDIATE":
        return params

    actions_map = params.get("actions", {})
    agent_key = str(agent_id)
    agent_actions = actions_map.get(agent_key, [])

    return {
        "remediation_plan_id": params.get("remediation_plan_id"),
        "operation": params.get("operation"),
        "actions": agent_actions,
    }

class AgentServicer:
    def __init__(self, db_factory, cache, nats) -> None:
        self.db_factory = db_factory
        self.cache = cache
        self.nats = nats

    async def HeartbeatStream(self, request_iterator, context):
        """Bidirectional stream — one response per heartbeat received."""
        async for request in request_iterator:
            # ── Identity gate (docs/security/SECURITY_AUDIT.md CR-03) ─────────
            # The wire agent_id is untrusted. Bind it to the mTLS client cert
            # CN and refuse revoked identities. These aborts happen BEFORE the
            # try/except below so they propagate as real gRPC statuses instead
            # of being swallowed by the generic error handler.
            cert_cn = _peer_cert_common_name(context)
            if not cert_cn:
                logger.warning("HeartbeatStream: no peer certificate presented")
                await context.abort(
                    grpc.StatusCode.UNAUTHENTICATED, "client certificate required"
                )
                return
            requested_id = str(getattr(request, "agent_id", "") or "").strip()
            if not requested_id or requested_id.lower() != cert_cn.lower():
                logger.warning(
                    "HeartbeatStream identity mismatch: cert CN=%s requested agent_id=%s",
                    cert_cn,
                    requested_id,
                )
                await context.abort(
                    grpc.StatusCode.UNAUTHENTICATED,
                    "certificate does not match agent_id",
                )
                return
            if await self.cache.get_cached(_revoked_key(requested_id)):
                logger.warning("HeartbeatStream: revoked agent %s rejected", requested_id)
                await context.abort(grpc.StatusCode.PERMISSION_DENIED, "agent revoked")
                return

            # ── Certificate serial revocation (P11 CRL-lite) ─────────────────
            # One lookup per connection attempt, keyed by the handshake cert's
            # serial (server-side extraction — agent input is never trusted
            # for revocation state). Settings control compat/fail-closed.
            from lokilinux.config import get_settings

            _settings = get_settings()
            cert_serial = _peer_cert_serial(context)
            try:
                await assert_not_revoked(
                    self.cache,
                    cert_serial,
                    enabled=_settings.certificate_revocation_enabled,
                    fail_closed=_settings.certificate_revocation_fail_closed,
                )
            except CertificateRevoked:
                logger.warning(
                    "HeartbeatStream: revoked certificate %s for agent %s",
                    cert_serial, requested_id,
                )
                await context.abort(grpc.StatusCode.PERMISSION_DENIED, "certificate revoked")
                return
            except RevocationUnavailable:
                logger.error(
                    "HeartbeatStream: revocation store unavailable, fail-closed for agent %s",
                    requested_id,
                )
                await context.abort(grpc.StatusCode.UNAVAILABLE, "revocation check unavailable")
                return

            try:
                # The JSON codec yields a SimpleNamespace with only the keys the
                # agent actually sent — ip_address is optional, fall back to the
                # gRPC peer address.
                ip_address = getattr(request, "ip_address", None)
                if not ip_address and context is not None:
                    peer = getattr(context, "peer", lambda: "")() or ""
                    ip_address = (
                        peer.rsplit(":", 1)[0].removeprefix("ipv4:").removeprefix("ipv6:") or None
                    )

                system_status = getattr(request, "system_status", None)
                packages = getattr(request, "packages", None)
                health = getattr(request, "health", None)
                job_results = getattr(request, "job_results", None)
                _count_agent_rejections(job_results)
                vulnerabilities = getattr(request, "vulnerabilities", None)

                # Identity binding happens in the gate ABOVE the try block
                # (CR-03) — aborts there propagate as real gRPC statuses; a
                # duplicate check here would be both redundant and swallowed
                # by this generic handler, so it lives only at the gate.

                async with self.db_factory() as db:
                    svc = AgentService(db, self.cache)
                    agent_version = getattr(request, "agent_version", None)
                    try:
                        agent = await svc.update_heartbeat(
                            request.agent_id,
                            {
                                "ip_address": ip_address,
                                "system_status": _as_dict(system_status),
                                "packages": [_as_dict(p) for p in (packages or [])],
                                "packages_checksum": getattr(request, "packages_checksum", None),
                                "health": _as_dict(health),
                                "job_results": [_as_dict(r) for r in (job_results or [])],
                                "vulnerabilities": [_as_dict(v) for v in (vulnerabilities or [])],
                                "agent_version": agent_version,
                                "recent_logs": getattr(request, "recent_logs", None),
                                "log_connections": getattr(request, "log_connections", None),
                                "log_informative": getattr(request, "log_informative", None),
                                "log_critical": getattr(request, "log_critical", None),
                            },
                        )
                    except ValueError as exc:
                        # Orphaned agent (row deleted, e.g. deregistered) that keeps
                        # reconnecting — an expected condition, not a bug. Rejecting
                        # the stream with a real status tells a well-behaved client
                        # to stop retrying; logging at warning (no traceback) instead
                        # of letting it fall to the except Exception below avoids an
                        # ERROR-level stack trace on every single heartbeat forever.
                        logger.warning("HeartbeatStream: %s", exc)
                        await context.abort(grpc.StatusCode.NOT_FOUND, str(exc))
                        return

                    # Observability pipeline (Task A5) — best-effort, never
                    # blocks or fails the heartbeat itself.
                    if await is_pipeline_enabled(self.cache, db):
                        await emit(self.nats, "agent", "host.heartbeat.ok", host_id=str(agent.id))
                        health_raw = _as_dict(health)
                        health_dict: dict = health_raw if isinstance(health_raw, dict) else {}
                        if health_dict:
                            await emit(
                                self.nats, "metrics", "metric.sample", host_id=str(agent.id),
                                payload={
                                    "cpu": health_dict.get("cpu_usage"),
                                    "memory": health_dict.get("memory_usage"),
                                    "disk": health_dict.get("disk_usage"),
                                },
                            )

                    pending_jobs = await svc.get_pending_jobs(agent.id)
                    job_timeouts = {
                        j.id: await get_job_timeout_seconds(db, j) for j in pending_jobs
                    }
                    # Signed envelopes attach only to privileged job types for
                    # agents new enough to validate them (job_envelope module
                    # handles gating; failures degrade to unsigned, never drop).
                    signed_params = {
                        j.id: maybe_attach_envelope(
                            j, _parameters_for_agent(j, agent.id), agent_version
                        )
                        for j in pending_jobs
                    }
                    # Attach signed approval claims to jobs that require them
                    # (plan §6): the agent verifies claim binding + signature
                    # before executing require_approval capabilities.
                    from sqlalchemy import select as _select
                    from lokilinux.models.approval import ApprovalClaim

                    attached_count = sum(
                        1 for p in signed_params.values() if "_envelope" in p
                    )
                    metrics.signed_jobs_total.inc(attached_count)
                    if pending_jobs:
                        logger.info(
                            "dispatch envelope summary: jobs=%d signed=%d agent_version=%s",
                            len(pending_jobs), attached_count, agent_version,
                        )
                    for j in pending_jobs:
                        if not getattr(j, "requires_approval", False):
                            continue
                        row = (
                            await db.execute(
                                _select(ApprovalClaim)
                                .where(ApprovalClaim.job_id == j.id,
                                       ApprovalClaim.consumed_at.is_(None))
                                .order_by(ApprovalClaim.created_at.desc())
                                .limit(1)
                            )
                        ).scalar_one_or_none()
                        if row is not None:
                            import json as _json
                            params_dict = dict(signed_params[j.id])
                            params_dict["_approval_claim"] = _json.loads(row.claim_json)
                            signed_params[j.id] = params_dict

                    # Compliance delta sync (docs/compliance/04-PROTOCOL.md §3) —
                    # domain_hashes/domain_full arrive as SimpleNamespace via the
                    # JSON codec's object_hook, same as system_status above.
                    # _as_dict's return type is broad (dict | list, recursively,
                    # same as system_status/packages above) — isinstance guards
                    # against malformed input rather than trusting the wire shape.
                    domain_hashes_raw = _as_dict(getattr(request, "domain_hashes", None))
                    domain_hashes: dict = (
                        domain_hashes_raw if isinstance(domain_hashes_raw, dict) else {}
                    )
                    domain_full_raw = _as_dict(getattr(request, "domain_full", None))
                    domain_full: dict = domain_full_raw if isinstance(domain_full_raw, dict) else {}

                    resync_domains: list[str] = []
                    if domain_hashes:
                        resync_domains = await diff_domain_hashes(db, agent.id, domain_hashes)
                        await publish_domain_hashes(self.nats, agent.id, domain_hashes)
                    if domain_full:
                        await publish_domain_snapshots(
                            self.nats, agent.id, domain_full, domain_hashes
                        )

                yield {
                    "pending_jobs": [
                        {
                            "job_id": str(j.id),
                            "job_type": j.job_type,
                            "parameters": signed_params[j.id],
                            **({"timeout_seconds": job_timeouts[j.id]} if job_timeouts.get(j.id) else {}),
                        }
                        for j in pending_jobs
                    ],
                    "resync_domains": resync_domains,
                }
            except Exception:
                logger.error("HeartbeatStream error", exc_info=True)
