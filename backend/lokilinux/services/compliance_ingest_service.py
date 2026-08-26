"""
LokiLinux — Compliance ingest: bridges the agent heartbeat's per-domain
delta-sync fields (domain_hashes/domain_full) to the NATS subjects the
lokilinux-compliance Go service consumes.

See docs/compliance/04-PROTOCOL.md §3 for the wire design this implements.
Content-hash *verification* deliberately isn't duplicated here — the Go
service's Ingester (services/compliance/internal/ingest/ingest.go)
independently recomputes BLAKE3 over the canonical JSON encoding and
rejects a mismatch, so this module only needs to relay what the agent
claimed, not re-derive it in a third language.
"""

import json
import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.models.inventory import InventorySnapshot
from lokilinux.nats_topics import COMPLIANCE_SNAPSHOT_DOMAIN

logger = logging.getLogger(__name__)


async def diff_domain_hashes(db: AsyncSession, agent_id: UUID, domain_hashes: dict) -> list[str]:
    """Compare the agent's claimed per-domain hashes against the latest
    stored snapshot for that agent/domain. Returns domains that are
    missing entirely or whose hash has changed — the agent sends a full
    body for each of these (domain_full) on its *next* heartbeat.
    """
    if not domain_hashes:
        return []

    result = await db.execute(
        select(InventorySnapshot.domain, InventorySnapshot.content_hash)
        .where(InventorySnapshot.agent_id == agent_id)
        .distinct(InventorySnapshot.domain)
        .order_by(InventorySnapshot.domain, InventorySnapshot.taken_at.desc())
    )
    known: dict[str, str] = dict(result.all())  # type: ignore[arg-type]  # SQLAlchemy Row unpacks fine at runtime

    return [
        domain
        for domain, claimed_hash in domain_hashes.items()
        if known.get(domain) != claimed_hash
    ]


async def publish_domain_snapshots(
    nats,
    agent_id: UUID,
    domain_full: dict,
    domain_hashes: dict,
) -> None:
    """Publish one lokilinux.compliance.snapshot.{domain} message per
    domain present in domain_full, pairing each with the hash the agent
    reported for that same domain in this heartbeat's domain_hashes.
    """
    for domain, facts in domain_full.items():
        content_hash = domain_hashes.get(domain, "")
        if not content_hash:
            logger.warning(
                "domain_full entry for %s has no matching domain_hashes entry — skipping publish",
                domain,
            )
            continue
        await nats.publish(
            f"{COMPLIANCE_SNAPSHOT_DOMAIN}.{domain}",
            json.dumps(
                {
                    "agent_id": str(agent_id),
                    "domain": domain,
                    "content_hash": content_hash,
                    "facts": facts,
                }
            ).encode(),
        )
