"""
LokiLinux — HeartbeatMonitorWorker: periodic stale-heartbeat sweep.

Not NATS-driven like the other workers — runs its own asyncio loop, since
there's no event to subscribe to (absence of a heartbeat isn't an event).
Marks ACTIVE agents whose last_heartbeat exceeds fleet.heartbeat_timeout_minutes
as INACTIVE via AgentService.mark_inactive (pre-existing method, previously
unused — see agent_service.py) and publishes lokilinux.agent.unhealthy so the
pre-existing AlertProcessorWorker raises the alert, same as it already does
for any other unhealthy-agent signal.
"""

import asyncio
import json
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import select

from lokilinux.models.agent import Agent, AgentStatus
from lokilinux.nats_topics import AGENT_UNHEALTHY
from lokilinux.services.agent_service import AgentService
from lokilinux.settings_schema import get_setting_value

logger = structlog.get_logger()

_SWEEP_INTERVAL_SECONDS = 60


class HeartbeatMonitorWorker:
    def __init__(self, nats_client, db_session_factory, cache) -> None:
        self.nats = nats_client
        self.db_factory = db_session_factory
        self.cache = cache
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._loop())
        logger.info("HeartbeatMonitorWorker started")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()

    async def _loop(self) -> None:
        while True:
            try:
                await self._sweep()
            except Exception:
                logger.error("heartbeat_monitor.sweep_failed", exc_info=True)
            await asyncio.sleep(_SWEEP_INTERVAL_SECONDS)

    async def _sweep(self) -> None:
        async with self.db_factory() as db:
            timeout_minutes = await get_setting_value(db, "fleet.heartbeat_timeout_minutes")
            cutoff = datetime.now(timezone.utc) - timedelta(minutes=timeout_minutes)

            stale = (
                await db.execute(
                    select(Agent).where(Agent.status == AgentStatus.ACTIVE, Agent.last_heartbeat < cutoff)
                )
            ).scalars().all()

            if not stale:
                return

            svc = AgentService(db, self.cache)
            for agent in stale:
                await svc.mark_inactive(agent.id)
                logger.info("agent.marked_inactive", agent_id=str(agent.id), last_heartbeat=str(agent.last_heartbeat))
                try:
                    await self.nats.publish(
                        AGENT_UNHEALTHY,
                        json.dumps({"agent_id": str(agent.id), "hostname": agent.hostname or agent.agent_id}).encode(),
                    )
                except Exception:
                    logger.warning("heartbeat_monitor.nats_publish_failed", agent_id=str(agent.id), exc_info=True)
