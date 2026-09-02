"""
LokiLinux — Plugin service.
"""

import json
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.models.agent import Agent, AgentStatus
from lokilinux.models.plugin import Plugin, PluginInstallation, PluginStatus
from lokilinux.nats_topics import PLUGIN_INSTALL
from lokilinux.schemas.common import CursorPage
from lokilinux.schemas.plugin import PluginInstallationResponse, PluginResponse
from lokilinux.services.job_service import JobService


class PluginService:
    def __init__(self, db: AsyncSession, nats=None, cache=None):
        self.db = db
        self.nats = nats
        self.cache = cache

    async def list_plugins(self, limit: int = 20) -> CursorPage[PluginResponse]:
        rows = (await self.db.execute(
            select(Plugin).order_by(Plugin.created_at.desc()).limit(limit)
        )).scalars().all()
        total = (await self.db.execute(select(func.count()).select_from(Plugin))).scalar()
        return CursorPage(
            items=[PluginResponse.model_validate(p) for p in rows],
            total=total,
        )

    async def _get_or_404(self, plugin_id: UUID) -> Plugin:
        plugin = await self.db.get(Plugin, plugin_id)
        if not plugin:
            raise ValueError(f"Plugin {plugin_id} not found")
        return plugin

    async def install_plugin(
        self, plugin_id: UUID, agent_ids: list[UUID]
    ) -> list[PluginInstallationResponse]:
        plugin = await self._get_or_404(plugin_id)

        if plugin.plugin_type != "agent":
            # No agent-side component to install (control-plane / ui /
            # notification plugins run inside the platform, not on agents).
            # Complete synchronously — there is no roundtrip to wait for.
            plugin.installation_status = PluginStatus.INSTALLED
            plugin.is_installed = True
            plugin.installed_at = datetime.now(timezone.utc)
            await self.db.commit()
            return []

        if not agent_ids:
            # UI has no agent picker — default an agent-type plugin to the
            # whole active fleet.
            agent_ids = (await self.db.execute(
                select(Agent.id).where(Agent.status == AgentStatus.ACTIVE)
            )).scalars().all()
            if not agent_ids:
                raise ValueError("No active agents to install the plugin on")

        if not plugin.source_url:
            raise ValueError(
                f"Plugin {plugin.name} has no source_url — nothing for agents to download"
            )

        # Retry path: drop stale installation rows for these agents so a
        # re-install after INSTALLING_FAILED starts clean.
        await self.db.execute(
            delete(PluginInstallation).where(
                PluginInstallation.plugin_id == plugin_id,
                PluginInstallation.agent_id.in_(agent_ids),
            )
        )

        installations = []
        for agent_id in agent_ids:
            inst = PluginInstallation(
                plugin_id=plugin_id,
                agent_id=agent_id,
                status="PENDING_INSTALL",
                installed_version=plugin.version,
            )
            self.db.add(inst)
            installations.append(inst)

        plugin.installation_status = PluginStatus.INSTALLING
        await self.db.flush()  # populate server-default ids before serialization
        responses = [PluginInstallationResponse.model_validate(i) for i in installations]

        # Deliver through the existing job pipeline: create_job fans out a
        # JobResult per agent, agents pick it up on heartbeat, and
        # recompute_job_status syncs the results back into PluginInstallation
        # rows (see job_service._sync_plugin_installations). create_job
        # commits the session, covering our mutations above too.
        job_svc = JobService(self.db, self.cache, self.nats)
        await job_svc.create_job(
            name=f"Install plugin {plugin.name} v{plugin.version}",
            job_type="PLUGIN_INSTALL",
            target_servers={"agent_ids": [str(a) for a in agent_ids]},
            parameters={
                "plugin_id": str(plugin_id),
                "plugin_name": plugin.name,
                "plugin_version": plugin.version,
                "download_url": plugin.source_url,
                "checksum_sha256": plugin.checksum or "",
            },
        )

        # Publish after commit: a failed commit must not emit an install event
        # for a rolled-back installation (transaction safety).
        if self.nats:
            await self.nats.publish(
                PLUGIN_INSTALL,
                json.dumps({
                    "plugin_id": str(plugin_id),
                    "agent_ids": [str(a) for a in agent_ids],
                }).encode(),
            )

        return responses

    async def enable_plugin(self, plugin_id: UUID) -> PluginResponse:
        plugin = await self._get_or_404(plugin_id)
        allowed = {PluginStatus.INSTALLED, PluginStatus.DISABLED}
        if plugin.installation_status not in allowed:
            allowed_str = " or ".join(s.value for s in allowed)
            raise ValueError(
                f"Plugin must be {allowed_str} to enable, got {plugin.installation_status.value}"
            )
        plugin.is_enabled = True
        plugin.installation_status = PluginStatus.ENABLED
        plugin.last_enabled_at = datetime.now(timezone.utc)
        await self.db.commit()
        return PluginResponse.model_validate(plugin)

    async def disable_plugin(self, plugin_id: UUID) -> PluginResponse:
        plugin = await self._get_or_404(plugin_id)
        plugin.is_enabled = False
        plugin.installation_status = PluginStatus.DISABLED
        plugin.last_disabled_at = datetime.now(timezone.utc)
        await self.db.commit()
        return PluginResponse.model_validate(plugin)

