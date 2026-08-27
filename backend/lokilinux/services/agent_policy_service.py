"""
LokiLinux — Agent policy distribution helpers (HeartbeatStream side).

Closed loop over the existing mTLS gRPC connection — no separate push
channel needed:
    deploy stamps pending + desired version on the agent row
      → heartbeat response embeds the signed envelope once (delivered)
        → agent verifies/commits, reports back via the NEXT heartbeat's
          policy_report field
        → report marks the deployment applied/failed and updates the
          agents row's actual state.

Deviation from plan §5 documented: NATS notify stays best-effort CP-internal;
the authoritative transport is the heartbeat itself, so remote agents behind
NAT work with zero new connections.
"""

import json as _json
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.cache import RedisCache
from lokilinux.models.agent import Agent
from lokilinux.models.agent_policy import AgentPolicyDeployment, DeploymentStatus

logger = logging.getLogger(__name__)

DEPLOYMENT_TTL_SECONDS = 86400  # give up refreshing an envelope after a day


async def _pending_policy_envelope(db: AsyncSession, agent: Agent) -> dict | None:
    """Returns the wire envelope for a pending deployment, marking it
    delivered; None when nothing pending. The envelope embeds everything the
    agent needs to verify: payload (canonical), hash, signature, key id."""
    deployment = (
        await db.execute(
            select(AgentPolicyDeployment)
            .where(
                AgentPolicyDeployment.agent_id == agent.id,
                AgentPolicyDeployment.status == "pending",
            )
            .order_by(AgentPolicyDeployment.started_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if not deployment:
        return None

    from lokilinux.models.agent_policy import AgentPolicyVersion

    version = await db.get(AgentPolicyVersion, deployment.version_id)
    if version is None or not version.signature:
        logger.error("policy deployment %s has unsigned/missing version", deployment.id)
        return None

    payload_raw = _json.dumps(version.payload, sort_keys=True, separators=(",", ":"))
    envelope = {
        "deployment_id": str(deployment.id),
        "policy_id": str(version.policy_id),
        "version": version.version,
        "hash": version.payload_hash,
        "signature": version.signature,
        "signing_key_id": version.signing_key_id,
        # Payload travels as canonical STRING bytes, not a nested object — the
        # agent hashes/signature-verifies these exact bytes without ever
        # re-serializing (re-marshaling on either side could reorder keys).
        "payload": payload_raw,
    }
    deployment.status = "delivered"
    agent.policy_status = "syncing"
    return envelope


async def _apply_policy_report(
    db: AsyncSession, agent: Agent, cache: RedisCache, report: dict
) -> None:
    """Records a policy apply/failed report coming from the agent."""
    result = str(report.get("result", ""))
    if result not in ("applied", "failed"):
        return
    deployment_id = str(report.get("deployment_id", "") or "")
    query = select(AgentPolicyDeployment).where(
        AgentPolicyDeployment.agent_id == agent.id
    ).order_by(AgentPolicyDeployment.started_at.desc()).limit(5)
    deployments = (await db.execute(query)).scalars().all()
    target = None
    for d in deployments:
        if deployment_id and str(d.id) == deployment_id:
            target = d
            break
    if target is None and deployments:
        candidate = [d for d in deployments if d.status == "delivered"]
        target = candidate[0] if candidate else None
    if target is None:
        logger.warning("policy report for unknown/stale deployment ignored: agent=%s", agent.id)
        return

    try:
        version_num = int(report.get("version", 0))
    except (TypeError, ValueError):
        version_num = 0

    now = datetime.now(timezone.utc)
    if result == "applied":
        target.status = "applied"
        target.finished_at = now
        agent.current_policy_version_id = target.version_id
        agent.policy_status = "idle"
        agent.policy_last_error = None
        agent.policy_updated_at = now
        # prune stale sibling deployments for the same policy at the same version
        await db.execute(
            sa_update(AgentPolicyDeployment)
            .where(
                AgentPolicyDeployment.agent_id == agent.id,
                AgentPolicyDeployment.status.in_(["pending", "delivered"]),
                AgentPolicyDeployment.version_id == target.version_id,
                AgentPolicyDeployment.id != target.id,
            )
            .values(status=DeploymentStatus.APPLIED.value, finished_at=now)
        )
        logger.info("policy applied: agent=%s version=%s", agent.agent_id, version_num)
    else:
        target.status = "failed"
        target.error = str(report.get("error", ""))[:500]
        target.finished_at = now
        agent.policy_status = "failed"
        agent.policy_last_error = target.error
        agent.desired_policy_version_id = (
            agent.current_policy_version_id
        )  # freeze desired at last-good so we don't re-push the broken doc forever
        logger.warning(
            "policy apply failed: agent=%s error=%s", agent.agent_id, target.error
        )

    await cache.invalidate_pattern(f"agent:*{agent.id}*")
