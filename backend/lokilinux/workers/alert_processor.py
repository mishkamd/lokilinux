"""
LokiLinux — AlertProcessorWorker: NATS consumer for agent unhealthy events.

Subscribes to lokilinux.agent.unhealthy.
Expected payload: {"agent_id": str, "hostname": str}
"""

import json
import logging
from uuid import UUID

from lokilinux.nats_topics import AGENT_UNHEALTHY
from lokilinux.services.alert_service import AlertService

logger = logging.getLogger(__name__)


class AlertProcessorWorker:
    def __init__(self, nats_client, db_session_factory) -> None:
        self.nats = nats_client
        self.db_factory = db_session_factory

    async def start(self) -> None:
        await self.nats.subscribe(AGENT_UNHEALTHY, cb=self._handle_unhealthy)
        logger.info("AlertProcessorWorker started")

    async def _handle_unhealthy(self, msg) -> None:
        try:
            data = json.loads(msg.data)
            agent_id = UUID(data["agent_id"])
            hostname = data.get("hostname", data["agent_id"])
            async with self.db_factory() as db:
                svc = AlertService(db, self.nats)
                await svc.create_alert(
                    title=f"Agent {hostname} UNHEALTHY",
                    description="Agent has stopped sending heartbeats",
                    severity="HIGH",
                    alert_type="AGENT_OFFLINE",
                    agent_id=agent_id,
                )
        except Exception:
            logger.error("Failed to process unhealthy event", exc_info=True)
