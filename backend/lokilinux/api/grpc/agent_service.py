"""
LokiLinux — gRPC AgentServicer: bidirectional heartbeat stream.

Inherits from proto-generated AgentServiceServicer once proto/ is compiled.
Until then this is a standalone class wiring AgentService into the gRPC layer.

Heartbeat flow:
  agent → HeartbeatRequest(agent_id, ip_address, system_info)
  server → HeartbeatResponse(pending_jobs, policy_delta)
"""

import logging

from lokilinux.services.agent_service import AgentService
from lokilinux.services.compliance_ingest_service import (
    diff_domain_hashes,
    publish_domain_hashes,
    publish_domain_snapshots,
)

logger = logging.getLogger(__name__)


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


class AgentServicer:
    def __init__(self, db_factory, cache, nats) -> None:
        self.db_factory = db_factory
        self.cache = cache
        self.nats = nats

    async def HeartbeatStream(self, request_iterator, context):
        """Bidirectional stream — one response per heartbeat received."""
        async for request in request_iterator:
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

                async with self.db_factory() as db:
                    svc = AgentService(db, self.cache)
                    agent = await svc.update_heartbeat(
                        request.agent_id,
                        {
                            "ip_address": ip_address,
                            "system_status": _as_dict(system_status),
                            "packages": [_as_dict(p) for p in (packages or [])],
                            "packages_checksum": getattr(request, "packages_checksum", None),
                            "health": _as_dict(health),
                            "job_results": [_as_dict(r) for r in (job_results or [])],
                            "agent_version": getattr(request, "agent_version", None),
                            "recent_logs": getattr(request, "recent_logs", None),
                            "log_connections": getattr(request, "log_connections", None),
                            "log_informative": getattr(request, "log_informative", None),
                            "log_critical": getattr(request, "log_critical", None),
                        },
                    )
                    pending_jobs = await svc.get_pending_jobs(agent.id)

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
                            "parameters": j.parameters or {},
                        }
                        for j in pending_jobs
                    ],
                    "resync_domains": resync_domains,
                }
            except Exception:
                logger.error("HeartbeatStream error", exc_info=True)
