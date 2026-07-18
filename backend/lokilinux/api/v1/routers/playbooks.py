"""
LokiLinux — Ansible Playbooks router (Automation Engine plugin).

Every route requires the "ansible-automation" Plugin row to be is_enabled —
disabling the plugin from /plugins immediately locks out playbook management
and execution (403), matching the install/activate/deactivate requirement.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.auth.dependencies import get_current_user, require_role, safe_user_uuid
from lokilinux.cache import RedisCache
from lokilinux.dependencies import get_cache, get_db, get_nats
from lokilinux.models.plugin import Plugin
from lokilinux.schemas.job import JobResponse
from lokilinux.schemas.playbook import (
    PlaybookCreate,
    PlaybookExecuteRequest,
    PlaybookResponse,
    PlaybookUpdate,
)
from lokilinux.services.playbook_service import PlaybookService

router = APIRouter()

ANSIBLE_PLUGIN_NAME = "ansible-automation"


def require_plugin_enabled(name: str):
    """Dependency factory — 403 if the named Plugin row is not is_enabled.

    ponytail: one query per request, no caching — playbook routes are low
    traffic (admin CRUD + execute) compared to job/agent heartbeat paths
    that already cache aggressively. Add caching only if this shows up
    as a hot path.
    """
    async def _check(db: AsyncSession = Depends(get_db)) -> None:
        plugin = (
            await db.execute(select(Plugin).where(Plugin.name == name))
        ).scalar_one_or_none()
        if plugin is None or not plugin.is_enabled:
            raise HTTPException(status_code=403, detail=f"Plugin '{name}' is not enabled")
    return _check


def _svc(
    db: AsyncSession = Depends(get_db),
    cache: RedisCache = Depends(get_cache),
    nats=Depends(get_nats),
) -> PlaybookService:
    return PlaybookService(db, cache, nats)


@router.get("", response_model=list[PlaybookResponse], dependencies=[Depends(require_plugin_enabled(ANSIBLE_PLUGIN_NAME))])
async def list_playbooks(
    svc: PlaybookService = Depends(_svc),
    _: dict = Depends(get_current_user),
) -> list[PlaybookResponse]:
    rows = await svc.list_playbooks()
    return [PlaybookResponse.model_validate(p) for p in rows]


@router.post("", response_model=PlaybookResponse, status_code=201, dependencies=[Depends(require_plugin_enabled(ANSIBLE_PLUGIN_NAME))])
async def create_playbook(
    body: PlaybookCreate,
    svc: PlaybookService = Depends(_svc),
    current_user: dict = Depends(require_role("ADMIN", "OPERATOR")),
) -> PlaybookResponse:
    playbook = await svc.create_playbook(
        name=body.name,
        content=body.content,
        description=body.description,
        default_extra_vars=body.default_extra_vars,
        created_by=safe_user_uuid(current_user),
        role_ids=body.role_ids,
        project_id=body.project_id,
    )
    return PlaybookResponse.model_validate(playbook)


@router.get("/{playbook_id}", response_model=PlaybookResponse, dependencies=[Depends(require_plugin_enabled(ANSIBLE_PLUGIN_NAME))])
async def get_playbook(
    playbook_id: UUID,
    svc: PlaybookService = Depends(_svc),
    _: dict = Depends(get_current_user),
) -> PlaybookResponse:
    try:
        playbook = await svc.get_playbook(playbook_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return PlaybookResponse.model_validate(playbook)


@router.patch("/{playbook_id}", response_model=PlaybookResponse, dependencies=[Depends(require_plugin_enabled(ANSIBLE_PLUGIN_NAME))])
async def update_playbook(
    playbook_id: UUID,
    body: PlaybookUpdate,
    svc: PlaybookService = Depends(_svc),
    _: dict = Depends(require_role("ADMIN", "OPERATOR")),
) -> PlaybookResponse:
    try:
        fields_set = body.model_fields_set
        playbook = await svc.update_playbook(
            playbook_id,
            name=body.name,
            description=body.description,
            content=body.content,
            default_extra_vars=body.default_extra_vars,
            is_enabled=body.is_enabled,
            role_ids=body.role_ids,
            project_id=body.project_id,
            clear_project="project_id" in fields_set and body.project_id is None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return PlaybookResponse.model_validate(playbook)


@router.delete("/{playbook_id}", status_code=204, dependencies=[Depends(require_plugin_enabled(ANSIBLE_PLUGIN_NAME))])
async def delete_playbook(
    playbook_id: UUID,
    svc: PlaybookService = Depends(_svc),
    _: dict = Depends(require_role("ADMIN", "OPERATOR")),
) -> None:
    try:
        await svc.delete_playbook(playbook_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{playbook_id}/execute", response_model=JobResponse, status_code=201, dependencies=[Depends(require_plugin_enabled(ANSIBLE_PLUGIN_NAME))])
async def execute_playbook(
    playbook_id: UUID,
    body: PlaybookExecuteRequest,
    svc: PlaybookService = Depends(_svc),
    current_user: dict = Depends(require_role("ADMIN", "OPERATOR")),
) -> JobResponse:
    try:
        job = await svc.execute_playbook(
            playbook_id,
            agent_ids=body.agent_ids,
            extra_vars=body.extra_vars,
            created_by=safe_user_uuid(current_user),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return JobResponse.model_validate(job)
