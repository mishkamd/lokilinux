"""
LokiLinux — PluginWorker: NATS consumer for plugin install events.

Subscribes to lokilinux.plugin.install.
Expected payload: {"plugin_id": str, "agent_ids": [str]}

Tracks which agents have a pending plugin install and invalidates cached
plugin/agent lists so dashboards reflect the in-progress installation. The
agents pick up the actual install action on their next heartbeat.
"""

import json
import logging

from lokilinux.nats_topics import PLUGIN_INSTALL

logger = logging.getLogger(__name__)


class PluginWorker:
    def __init__(self, nats_client, db_session_factory, cache) -> None:
        self.nats = nats_client
        self.db_factory = db_session_factory
        self.cache = cache

    async def start(self) -> None:
        await self.nats.subscribe(PLUGIN_INSTALL, cb=self._handle_plugin_install)
        logger.info("PluginWorker started")

    async def _handle_plugin_install(self, msg) -> None:
        try:
            data = json.loads(msg.data)
            plugin_id = data.get("plugin_id", "unknown")
            agent_ids = data.get("agent_ids", [])
            logger.info(
                "plugin.install received",
                extra={"plugin_id": plugin_id, "agent_count": len(agent_ids)},
            )

            # Invalidate cached plugin/agent views so the INSTALLING state is visible
            await self.cache.invalidate_pattern("plugin:list:*")
            await self.cache.invalidate_pattern(f"plugin:{plugin_id}:*")
        except Exception:
            logger.error("Failed to process plugin.install event", exc_info=True)
