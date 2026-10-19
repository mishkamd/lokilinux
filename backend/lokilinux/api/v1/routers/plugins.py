"""
LokiLinux — Plugins router.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.auth.dependencies import get_current_user, require_role
from lokilinux.dependencies import get_cache, get_db, get_nats
from lokilinux.schemas.common import CursorPage
from lokilinux.schemas.plugin import PluginInstallationResponse, PluginResponse
from lokilinux.services.plugin_service import PluginService

router = APIRouter()


def _svc(
    db: AsyncSession = Depends(get_db),
    cache=Depends(get_cache),
    nats=Depends(get_nats),
) -> PluginService:
    return PluginService(db, nats=nats, cache=cache)


@router.get("", response_model=CursorPage[PluginResponse])
async def list_plugins(
    limit: int = Query(20, ge=1, le=100),
    svc: PluginService = Depends(_svc),
    _: dict = Depends(get_current_user),
) -> CursorPage[PluginResponse]:
    return await svc.list_plugins(limit)


@router.post("/{plugin_id}/install", response_model=list[PluginInstallationResponse])
async def install_plugin(
    plugin_id: UUID,
    agent_ids: list[UUID],
    svc: PluginService = Depends(_svc),
    _: dict = Depends(require_role("ADMIN", "OPERATOR")),
) -> list[PluginInstallationResponse]:
    try:
        return await svc.install_plugin(plugin_id, agent_ids)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{plugin_id}/enable", response_model=PluginResponse)
async def enable_plugin(
    plugin_id: UUID,
    svc: PluginService = Depends(_svc),
    _: dict = Depends(require_role("ADMIN", "OPERATOR")),
) -> PluginResponse:
    try:
        return await svc.enable_plugin(plugin_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{plugin_id}/disable", response_model=PluginResponse)
async def disable_plugin(
    plugin_id: UUID,
    svc: PluginService = Depends(_svc),
    _: dict = Depends(require_role("ADMIN", "OPERATOR")),
) -> PluginResponse:
    try:
        return await svc.disable_plugin(plugin_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

