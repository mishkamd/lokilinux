"""
LokiLinux — DSC ingest: bridges the agent heartbeat's per-resource-type
delta-sync fields (dsc_resource_hashes/dsc_resource_full) to the NATS
subjects the lokilinux-dsc Go service consumes.

Mirrors compliance_ingest_service.py exactly — same delta-sync shape one
level more granular (docs/dsc/05-PROTOCOL.md). Content-hash *verification*
deliberately isn't duplicated here either — lokilinux-dsc's own ingest
pipeline independently recomputes BLAKE3 and rejects a mismatch, same
reasoning as the compliance predecessor.
"""

import json
import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.models.baseline import BaselineEffective
from lokilinux.models.dsc import DscProviderStatus
from lokilinux.nats_topics import DSC_RESOURCE_HASHES_REPORTED, DSC_RESOURCE_SNAPSHOT

logger = logging.getLogger(__name__)


async def diff_resource_hashes(db: AsyncSession, agent_id: UUID, resource_hashes: dict) -> list[str]:
    """Compare the agent's claimed per-resource-type (type-level aggregate)
    hashes against the last-stored aggregate hash for that agent/type.
    Returns types that are missing entirely or whose hash has changed — the
    agent sends a full body for each of these (dsc_resource_full) on its
    *next* heartbeat.

    Reads dsc_provider_status.content_hash, not dsc_resource_states —
    dsc_resource_states.content_hash is per-resource-key (one row per
    resource, e.g. one sysctl parameter), so a query picking "the latest
    row per resource_type" returns an arbitrary single key's own hash, which
    can never equal the agent's type-level aggregate hash. That mismatch
    used to make every multi-key resource type resync in full on every
    heartbeat, forever. dsc_provider_status has exactly one row per (agent,
    resource_type) and is upserted with the same aggregate hash the agent
    sent, so this comparison can actually settle.
    """
    if not resource_hashes:
        return []

    result = await db.execute(
        select(DscProviderStatus.resource_type, DscProviderStatus.content_hash)
        .where(DscProviderStatus.agent_id == agent_id)
    )
    known: dict[str, str] = dict(result.all())  # type: ignore[arg-type]  # SQLAlchemy Row unpacks fine at runtime

    return [
        resource_type
        for resource_type, claimed_hash in resource_hashes.items()
        if known.get(resource_type) != claimed_hash
    ]


async def publish_resource_hashes(nats, agent_id: UUID, resource_hashes: dict) -> None:
    """Publish the raw per-resource-type hash report. lokilinux-dsc doesn't
    consume this subject at Phase 1 (it only consumes full snapshot bodies
    on DSC_RESOURCE_SNAPSHOT) — kept for parity with the compliance
    predecessor's documented wire contract so a future lightweight consumer
    doesn't need another protocol change to attach.
    """
    await nats.publish(
        DSC_RESOURCE_HASHES_REPORTED,
        json.dumps({"agent_id": str(agent_id), "resource_hashes": resource_hashes}).encode(),
    )


async def publish_resource_snapshots(
    nats,
    agent_id: UUID,
    resource_full: dict,
    resource_hashes: dict,
) -> None:
    """Publish one lokilinux.dsc.resource.snapshot.{resource_type} message
    per type present in resource_full. The payload's facts are keyed by
    resource_key (docs/dsc/01-RESOURCE-MODEL.md §2) — lokilinux-dsc
    decomposes this into individual dsc_resource_states rows, one per key,
    rather than one row per type (docs/dsc/05-PROTOCOL.md §4).
    """
    for resource_type, facts_by_key in resource_full.items():
        content_hash = resource_hashes.get(resource_type, "")
        if not content_hash:
            logger.warning(
                "dsc_resource_full entry for %s has no matching dsc_resource_hashes entry — skipping publish",
                resource_type,
            )
            continue
        await nats.publish(
            f"{DSC_RESOURCE_SNAPSHOT}.{resource_type}",
            json.dumps(
                {
                    "agent_id": str(agent_id),
                    "resource_type": resource_type,
                    "content_hash": content_hash,
                    "facts_by_key": facts_by_key,
                }
            ).encode(),
        )


async def get_desired_state_if_changed(db: AsyncSession, agent_id: UUID, client_hash: str) -> dict | None:
    """Returns the compiled desired-state document for agent_id if it
    differs from client_hash (the agent's cached hash) — None means
    "unchanged, don't resend" (docs/dsc/05-PROTOCOL.md §3). baseline_effective
    is written by lokilinux-dsc's leader-elected compiler loop
    (docs/dsc/06-GO-SERVICE.md §2); this only reads it — no writer here,
    matching the read-only role every other endpoint already gives this table.

    row is None covers two different situations that must not be conflated:
    a host never targeted by any DSC_DESIRED_STATE policy (client_hash is
    already "", nothing to tell it) vs. a host whose last targeting policy
    was just removed (compiler.py's DeleteStaleBaselineEffective already
    deletes the row — client_hash is still the stale non-empty value from
    when the policy existed). The second case must send an explicit
    empty-document response so the agent clears its cached desired state
    (ReconcileLoop.CheckDivergence) — confirmed live on devapp.mishka.md
    (agent 0.24.0) that silently returning None here leaves the agent
    warning about drift against a desired state that no longer exists,
    forever, since there is otherwise no signal that ever tells it to stop.
    """
    row = await db.get(BaselineEffective, agent_id)
    if row is None:
        if client_hash:
            return {"content_hash": "", "document": {}}
        return None
    if row.merged_hash == client_hash:
        return None
    return {"content_hash": row.merged_hash, "document": row.merged_state}
