"""
LokiLinux — gRPC AgentServicer: bidirectional heartbeat stream.

Inherits from proto-generated AgentServiceServicer once proto/ is compiled.
Until then this is a standalone class wiring AgentService into the gRPC layer.

Heartbeat flow:
  agent → HeartbeatRequest(agent_id, ip_address, system_info)
  server → HeartbeatResponse(pending_jobs, policy_delta)
"""

import base64
import gzip
import json
import logging
import re
from uuid import NAMESPACE_URL, uuid5

import grpc
from cryptography import x509
from cryptography.x509.oid import NameOID

from lokilinux.services.agent_service import (
    _JOB_STATE_TO_STATUS,
    PENDING_JOBS_PER_HEARTBEAT,
    AgentService,
)
from lokilinux.services.cert_revocation import (
    CertificateRevoked,
    RevocationUnavailable,
    assert_not_revoked,
)
from lokilinux.events.publish import emit, is_pipeline_enabled
from lokilinux.services.agent_policy_service import (
    _apply_policy_report,
    _pending_policy_envelope,
)
from lokilinux.services.compliance_ingest_service import (
    diff_domain_hashes,
    publish_domain_snapshots,
)
from lokilinux import metrics
from lokilinux.services.job_envelope import EnvelopeSigningError, maybe_attach_envelope
from lokilinux.services.job_service import parameters_for_agent
from lokilinux.services.policy_service import get_job_timeout_seconds
from lokilinux.services import fim_scope_service
from lokilinux.services.snapshot_hmac import key_for_agent as snapshot_key_for_agent
from lokilinux.utils.agent_capability import MIN_AGENT_VERSION_FIM_SCOPES, agent_meets_minimum

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


class _AuthGateFailure(Exception):
    """Carries the grpc status to abort with — raised by _authenticate_agent,
    caught at each RPC's own call site so it can abort its own context/stream."""

    def __init__(self, code: grpc.StatusCode, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(detail)


async def _authenticate_agent(context, requested_agent_id: str, cache, settings) -> None:
    """Identity gate shared by every RPC that trusts an agent_id claim
    (docs/security/SECURITY_AUDIT.md CR-03): binds it to the mTLS client
    cert CN, and rejects revoked identities/certs. Raises _AuthGateFailure
    on any failure — never returns a verdict, only succeeds or raises."""
    cert_cn = _peer_cert_common_name(context)
    if not cert_cn:
        logger.warning("auth gate: no peer certificate presented")
        raise _AuthGateFailure(grpc.StatusCode.UNAUTHENTICATED, "client certificate required")
    if not requested_agent_id or requested_agent_id.lower() != cert_cn.lower():
        logger.warning(
            "auth gate identity mismatch: cert CN=%s requested agent_id=%s",
            cert_cn, requested_agent_id,
        )
        raise _AuthGateFailure(
            grpc.StatusCode.UNAUTHENTICATED, "certificate does not match agent_id"
        )
    if await cache.get_cached(_revoked_key(requested_agent_id)):
        logger.warning("auth gate: revoked agent %s rejected", requested_agent_id)
        raise _AuthGateFailure(grpc.StatusCode.PERMISSION_DENIED, "agent revoked")

    # Certificate serial revocation (P11 CRL-lite) — one lookup per call,
    # keyed by the handshake cert's serial (server-side extraction only).
    cert_serial = _peer_cert_serial(context)
    try:
        await assert_not_revoked(
            cache,
            cert_serial,
            enabled=settings.certificate_revocation_enabled,
            fail_closed=settings.certificate_revocation_fail_closed,
        )
    except CertificateRevoked:
        logger.warning(
            "auth gate: revoked certificate %s for agent %s", cert_serial, requested_agent_id,
        )
        raise _AuthGateFailure(grpc.StatusCode.PERMISSION_DENIED, "certificate revoked")
    except RevocationUnavailable:
        logger.error(
            "auth gate: revocation store unavailable, fail-closed for agent %s",
            requested_agent_id,
        )
        raise _AuthGateFailure(grpc.StatusCode.UNAVAILABLE, "revocation check unavailable")


_REJECT_RE = re.compile(r"rejected \[(\w+)\]")


async def _emit_job_outcomes(nats, host_id: str, job_results: list[dict]) -> None:
    """Job outcomes reach the backend on the heartbeat (nothing publishes JOB_RESULT), so this
    is where job.completed / job.failed events — and through them job.failed signals — start."""
    for r in job_results:
        status = _JOB_STATE_TO_STATUS.get(r.get("state"))
        if not r.get("job_id") or status not in ("COMPLETED", "FAILED", "TIMEOUT"):
            continue  # not finished (or cancelled): nothing to report
        failed = status != "COMPLETED"
        await emit(
            nats, "job", "job.failed" if failed else "job.completed",
            severity="WARNING" if failed else "INFO", host_id=host_id,
            payload={"job_id": r["job_id"], "exit_code": r.get("exit_code"), "status": status},
            # Stable id: a result repeated on a later heartbeat is deduped by the processor.
            event_id=str(uuid5(NAMESPACE_URL, f"job-result:{r['job_id']}:{status}")),
        )


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

async def _select_approval_claim(db, job_id, wire_agent_id: str):
    """The approval claim served to this agent for a job (MIS-29 follow-up).

    A multi-target job carries one claim per target, bound to that agent's wire
    id, so the agent's own claim wins. A NULL target_agent_id claim is the legacy
    job-scoped form and is served only when no per-agent claim exists. consumed_at
    is filtered per row, so consuming one agent's claim never hides another's.
    """
    from sqlalchemy import select

    from lokilinux.models.approval import ApprovalClaim

    unconsumed = (
        select(ApprovalClaim)
        .where(ApprovalClaim.job_id == job_id, ApprovalClaim.consumed_at.is_(None))
        .order_by(ApprovalClaim.created_at.desc())
        .limit(1)
    )
    row = (
        await db.execute(unconsumed.where(ApprovalClaim.target_agent_id == wire_agent_id))
    ).scalar_one_or_none()
    if row is None:
        row = (
            await db.execute(unconsumed.where(ApprovalClaim.target_agent_id.is_(None)))
        ).scalar_one_or_none()
    return row

_COLLECTOR_POLICY_KEY = "observability.collector_policy"


async def _get_collector_policy(db) -> dict:
    """Global (fleet-wide) collector policy for Phase G2's SyncPolicy RPC —
    stored directly in the settings table, deliberately NOT routed through
    settings_schema.py's SETTINGS_SCHEMA (that system is for typed, admin
    UI-editable scalars; this is a machine-internal JSON blob with no admin
    UI in this phase). Same underlying table as the rest of platform
    settings, just bypassing the schema-validation layer. No write path
    exists yet — nothing in this phase sets this key, so an unset row
    means every agent gets an empty collector map (all defaults) until an
    operator or a future admin surface writes one."""
    from sqlalchemy import select

    from lokilinux.models.audit import Setting

    row = (
        await db.execute(select(Setting).where(Setting.key == _COLLECTOR_POLICY_KEY))
    ).scalar_one_or_none()
    if not row or not row.value:
        return {"version": "0", "collectors": {}}
    try:
        parsed = json.loads(row.value)
    except (TypeError, ValueError):
        logger.warning("collector_policy: stored value is not valid JSON, using empty default")
        return {"version": "0", "collectors": {}}
    if not isinstance(parsed, dict):
        return {"version": "0", "collectors": {}}
    parsed.setdefault("version", "0")
    parsed.setdefault("collectors", {})
    return parsed


class AgentServicer:
    def __init__(self, db_factory, cache, nats) -> None:
        self.db_factory = db_factory
        self.cache = cache
        self.nats = nats

    async def HeartbeatStream(self, request_iterator, context):
        """Bidirectional stream — one response per heartbeat received."""
        async for request in request_iterator:
            # ── Identity gate (docs/security/SECURITY_AUDIT.md CR-03) ─────────
            # The wire agent_id is untrusted. This abort happens BEFORE the
            # try/except below so it propagates as a real gRPC status instead
            # of being swallowed by the generic error handler.
            from lokilinux.config import get_settings

            _settings = get_settings()
            requested_id = str(getattr(request, "agent_id", "") or "").strip()
            try:
                await _authenticate_agent(context, requested_id, self.cache, _settings)
            except _AuthGateFailure as exc:
                await context.abort(exc.code, exc.detail)
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
                                "capabilities": list(getattr(request, "capabilities", None) or []),
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
                        await _emit_job_outcomes(
                            self.nats, str(agent.id), [_as_dict(r) for r in (job_results or [])]
                        )
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

                    # Signed envelopes attach only to privileged job types for
                    # agents new enough to validate them (job_envelope module
                    # handles gating). A job that qualifies but cannot be signed
                    # is held back from this heartbeat, never sent unsigned.
                    # Held jobs stay PENDING, so they would keep filling the pending window:
                    # ask again without the ids already seen, while a round held something back
                    # and the window is not full. Held ids get a hold (mark_held) after the loop,
                    # so later heartbeats skip them too. Still at most 10 sent per heartbeat.
                    # ponytail: no round cap, a 3-round cap starved agents with more than 30 held
                    # jobs. Cost is one query per 10 held jobs on a heartbeat; upgrade path is
                    # a held-job count per agent if that backlog ever gets large.
                    signed_params = {}
                    pending_jobs = []
                    job_timeouts = {}
                    seen: set = set()
                    held_ids: list = []
                    while len(pending_jobs) < PENDING_JOBS_PER_HEARTBEAT:
                        batch = await svc.get_pending_jobs(
                            agent.id, exclude_ids=seen,
                            limit=PENDING_JOBS_PER_HEARTBEAT - len(pending_jobs),
                        )
                        if not batch:
                            break
                        held_in_batch = False
                        for j in batch:
                            seen.add(j.id)
                            try:
                                signed_params[j.id] = maybe_attach_envelope(
                                    j, parameters_for_agent(j, agent.id), agent_version,
                                    # Envelope must carry the wire identity (Agent.agent_id),
                                    # not the PK — the agent validates envelope.agent_id
                                    # against what it reports in its own heartbeats, and
                                    # the two differ whenever re-enrollment assigned a new
                                    # PK for the same host (rocky: PK 9737…, identity 56c8…).
                                    agent_id=str(agent.agent_id),
                                )
                            except EnvelopeSigningError:
                                # Held: not dispatched, so it stays PENDING (never marked RUNNING,
                                # see mark_dispatched) and gets a hold from mark_held below.
                                logger.error(
                                    "job %s held for agent %s: envelope signing failed",
                                    j.id, agent.agent_id, exc_info=True,
                                )
                                held_ids.append(j.id)
                                held_in_batch = True
                                continue
                            pending_jobs.append(j)
                            job_timeouts[j.id] = await get_job_timeout_seconds(db, j)
                        if not held_in_batch:
                            break
                    await svc.mark_held(agent.id, held_ids)
                    # Attach signed approval claims to jobs that require them
                    # (plan §6): the agent verifies claim binding + signature
                    # before executing require_approval capabilities.
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
                        row = await _select_approval_claim(db, j.id, agent.agent_id)
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
                    domain_macs = _as_dict(getattr(request, "domain_macs", None))
                    reported_key_id = getattr(request, "snapshot_hmac_key_id", 0) or 0

                    resync_domains: list[str] = []
                    if domain_hashes:
                        resync_domains = await diff_domain_hashes(db, agent.id, domain_hashes)
                    if domain_full:
                        await publish_domain_snapshots(
                            self.nats, agent.id, domain_full, domain_hashes,
                            domain_macs if isinstance(domain_macs, dict) else None,
                        )

                    # Agent policy reconciliation (plan Faza 2): process the
                    # apply report from the previous cycle, then attach the
                    # desired envelope when a deployment is still pending.
                    policy_report_raw = _as_dict(getattr(request, "policy_report", None))
                    if isinstance(policy_report_raw, dict) and policy_report_raw.get("policy_id"):
                        await _apply_policy_report(
                            db, agent, self.cache, policy_report_raw
                        )

                    policy_envelope = await _pending_policy_envelope(
                        db, agent
                    )

                    # File-integrity watch/ignore scope (docs/compliance/
                    # 11a-FRONTEND-PAGES.md §3.4) — attached on every
                    # heartbeat, unlike policy_envelope: it must reach every
                    # agent, not just ones with a policy deployment. Gated
                    # on agent_version since older binaries' wire struct
                    # simply has no field for it (compile-down is automatic,
                    # this just skips a wasted sign_payload() call).
                    fim_config = None
                    if agent_meets_minimum(agent_version, MIN_AGENT_VERSION_FIM_SCOPES):
                        fim_scope = await fim_scope_service.resolve_for_agent(db, agent.id)
                        fim_config = fim_scope_service.signed_envelope(agent.id, fim_scope)

                    hmac_key = snapshot_key_for_agent(agent, reported_key_id)
                    # Last step before the yield. Only the jobs this heartbeat claims (PENDING to
                    # RUNNING) are sent; a concurrent heartbeat that already claimed one gets
                    # nothing back for it. Anything above that raises leaves them PENDING.
                    pending_jobs = await svc.mark_dispatched(agent.id, pending_jobs)
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
                        **({"policy_envelope": policy_envelope} if policy_envelope else {}),
                        **({"fim_config": fim_config} if fim_config else {}),
                        **({"snapshot_hmac": hmac_key} if hmac_key else {}),
                    }
            except Exception:
                logger.error("HeartbeatStream error", exc_info=True)

    async def RenewCertificate(self, request, context):
        """Issues a new short-lived cert for a keypair the agent generated
        locally — the mTLS handshake this RPC rides on is the proof of
        possession of the CURRENT key; renewal itself proves nothing about
        the NEW key, it's just a delivery channel authenticated by the old one.
        """
        from lokilinux.config import get_settings

        settings = get_settings()
        requested_id = str(getattr(request, "agent_id", "") or "").strip()
        try:
            await _authenticate_agent(context, requested_id, self.cache, settings)
        except _AuthGateFailure as exc:
            await context.abort(exc.code, exc.detail)
            return

        public_key_pem = str(getattr(request, "public_key_pem", "") or "")
        if not public_key_pem:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "public_key_pem required")
            return

        rate_key = f"cert_renewal:last:{requested_id}"
        if await self.cache.get_cached(rate_key):
            await context.abort(
                grpc.StatusCode.RESOURCE_EXHAUSTED, "renewal already issued recently"
            )
            return

        from lokilinux.services import ca_signer_client

        try:
            cert_pem = await ca_signer_client.sign_agent_cert(
                agent_id=requested_id,
                public_key_pem=public_key_pem,
                validity_days=settings.agent_cert_ttl_days,
            )
        except ca_signer_client.CASignerError:
            logger.error("RenewCertificate: signing failed for agent %s", requested_id, exc_info=True)
            await context.abort(grpc.StatusCode.UNAVAILABLE, "certificate signing unavailable")
            return

        await self.cache.set_cached(rate_key, True, ttl=3600)

        import os

        ca_cert_path = os.path.join(settings.agent_cert_dir, "ca.crt")
        with open(ca_cert_path) as f:
            ca_cert_pem = f.read()

        cert = x509.load_pem_x509_certificate(cert_pem.encode())
        not_after_unix = int(cert.not_valid_after_utc.timestamp())

        logger.info(
            "RenewCertificate: issued new cert for agent %s, not_after=%s",
            requested_id, cert.not_valid_after_utc.isoformat(),
        )
        return {
            "cert_pem": cert_pem,
            "ca_cert_pem": ca_cert_pem,
            "not_after_unix": not_after_unix,
        }

    async def ReportEvents(self, request_iterator, context):
        """Client-streaming (Phase G2): agent sends one or more gzip'd
        EventBatch messages, servicer publishes each record to NATS via the
        existing emit() helper, preserving the agent-issued event_id so
        EventProcessorWorker's set_nx dedup (Task A4) makes redelivery/
        retransmission idempotent end-to-end — see events/publish.py."""
        from lokilinux.config import get_settings

        settings = get_settings()
        accepted = 0
        authenticated = False

        async for batch in request_iterator:
            requested_id = str(getattr(batch, "agent_id", "") or "").strip()
            if not authenticated:
                try:
                    await _authenticate_agent(context, requested_id, self.cache, settings)
                except _AuthGateFailure as exc:
                    await context.abort(exc.code, exc.detail)
                    return {"accepted": False, "events_accepted": accepted, "error_message": exc.detail}
                authenticated = True

            raw_b64 = getattr(batch, "events_gzip", None)
            if not raw_b64:
                continue
            try:
                raw = gzip.decompress(base64.b64decode(raw_b64))
                records = json.loads(raw)
            except Exception:
                logger.warning("ReportEvents: malformed batch from %s", requested_id, exc_info=True)
                continue
            if not isinstance(records, list):
                continue

            for rec in records:
                if not isinstance(rec, dict):
                    continue
                rec_type = rec.get("type")
                if not rec_type:
                    continue
                try:
                    await emit(
                        self.nats,
                        source="agent",
                        type_=rec_type,
                        host_id=rec.get("host_id") or requested_id,
                        service=rec.get("service"),
                        severity=rec.get("severity") or "INFO",
                        payload=rec.get("payload") or {},
                        event_id=rec.get("event_id"),
                    )
                    accepted += 1
                except Exception:
                    logger.error("ReportEvents: emit failed for agent %s", requested_id, exc_info=True)

        return {"accepted": True, "events_accepted": accepted, "error_message": ""}

    async def SyncPolicy(self, request, context):
        """Unary (Phase G2): agent pulls the current global collector
        policy. Version comparison is the agent's job (it only rebuilds
        local collector state when the returned version differs from what
        it already has) — this RPC always returns the current policy."""
        from lokilinux.config import get_settings

        settings = get_settings()
        requested_id = str(getattr(request, "agent_id", "") or "").strip()
        try:
            await _authenticate_agent(context, requested_id, self.cache, settings)
        except _AuthGateFailure as exc:
            await context.abort(exc.code, exc.detail)
            return

        async with self.db_factory() as db:
            policy = await _get_collector_policy(db)

        return {
            "version": policy["version"],
            "collectors": policy["collectors"],
        }
