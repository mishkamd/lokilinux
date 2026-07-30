"""
LokiLinux — PolicyWorker: NATS consumer for policy change/apply events.

Subscribes to lokilinux.policy.changed and lokilinux.policy.apply.
- policy.changed payload: {"policy_id": str, "action": "created"|"updated"|"deleted"}
- policy.apply payload:   {"policy_id": str, "scope": {"all": bool} | {"agent_ids": [str, ...]}}

Both invalidate the Redis cache so dashboards/agent lookups reflect the
change; policy.apply additionally resolves scope to a concrete agent list
and records a PolicyAudit row — this is the Phase 0 prerequisite from
docs/compliance/00-OVERVIEW.md §6 ("A subscriber for lokilinux.policy.apply
— published today by routers/policies.py:175, consumed by nobody").
"""

import json
import logging
import uuid

from sqlalchemy import select

from lokilinux.models.agent import Agent
from lokilinux.models.policy import PolicyAudit
from lokilinux.nats_topics import POLICY_APPLY, POLICY_CHANGED

logger = logging.getLogger(__name__)


class PolicyWorker:
    def __init__(self, nats_client, db_session_factory, cache) -> None:
        self.nats = nats_client
        self.db_factory = db_session_factory
        self.cache = cache

    async def start(self) -> None:
        await self.nats.subscribe(POLICY_CHANGED, cb=self._handle_policy_changed)
        await self.nats.subscribe(POLICY_APPLY, cb=self._handle_policy_apply)
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

    async def _handle_policy_apply(self, msg) -> None:
        try:
            data = json.loads(msg.data)
            raw_policy_id = data.get("policy_id")
            try:
                policy_id = uuid.UUID(raw_policy_id)
            except (TypeError, ValueError):
                logger.error(
                    "policy.apply message has an invalid policy_id",
                    extra={"policy_id": raw_policy_id},
                )
                return
            scope = data.get("scope") or {}

            async with self.db_factory() as db:
                agent_ids = await self._resolve_scope(db, scope)

                db.add(
                    PolicyAudit(
                        policy_id=policy_id,
                        change_type="APPLIED",
                        new_value={"scope": scope, "matched_agents": len(agent_ids)},
                    )
                )
                await db.commit()

            logger.info(
                "policy.apply resolved",
                extra={"policy_id": policy_id, "matched_agents": len(agent_ids)},
            )
            await self.cache.invalidate_pattern(f"policy:{policy_id}:*")
        except Exception:
            logger.error("Failed to process policy.apply event", exc_info=True)

    async def _resolve_scope(self, db, scope: dict) -> list[str]:
        """Resolves an apply request's scope selector to concrete agent
        UUIDs. Supports {"all": true} and {"agent_ids": [...]} — the two
        shapes the frontend's policy-apply flow can produce today (no
        tag/group targeting exists on the Agent model yet).
        """
        if scope.get("all"):
            result = await db.execute(select(Agent.id))
            return [str(row) for row in result.scalars().all()]

        agent_ids = scope.get("agent_ids") or []
        if not agent_ids:
            logger.warning("policy.apply scope matched no agents", extra={"scope": scope})
        return [str(a) for a in agent_ids]
