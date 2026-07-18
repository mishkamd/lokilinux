"""
LokiLinux — PolicyWorker: NATS consumer for policy change events.

Subscribes to lokilinux.policy.changed.
Expected payload: {"policy_id": str, "action": "created"|"updated"|"deleted"}

Invalidates the Redis cache for all agents affected by the policy change
so the next heartbeat response carries the updated policy delta.
"""

import json
import logging

from lokilinux.nats_topics import POLICY_CHANGED

logger = logging.getLogger(__name__)


class PolicyWorker:
    def __init__(self, nats_client, db_session_factory, cache) -> None:
        self.nats = nats_client
        self.db_factory = db_session_factory
        self.cache = cache

    async def start(self) -> None:
        await self.nats.subscribe(POLICY_CHANGED, cb=self._handle_policy_changed)
        logger.info("PolicyWorker started")

    async def _handle_policy_changed(self, msg) -> None:
        try:
            data = json.loads(msg.data)
            policy_id = data.get("policy_id", "unknown")
            action = data.get("action", "unknown")
            logger.info("policy.changed received", extra={"policy_id": policy_id, "action": action})

            # Invalidate cached agent lists so dashboards reflect policy updates
            await self.cache.invalidate_pattern("server:list:*")
            await self.cache.invalidate_pattern(f"policy:{policy_id}:*")
        except Exception:
            logger.error("Failed to process policy.changed event", exc_info=True)
