"""
LokiLinux — Job Templates router (AWX "Job Template" equivalent).

Gated the same as /playbooks: requires the "ansible-automation" Plugin to
be is_enabled (see require_plugin_enabled in routers/playbooks.py).
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.auth.dependencies import get_current_user, require_role, safe_user_uuid
from lokilinux.api.v1.routers.playbooks import ANSIBLE_PLUGIN_NAME, require_plugin_enabled
from lokilinux.cache import RedisCache
from lokilinux.dependencies import get_cache, get_db, get_nats
from lokilinux.schemas.job import JobResponse
from lokilinux.schemas.playbook_template import (
    PlaybookTemplateCreate,
    PlaybookTemplateLaunchRequest,
    PlaybookTemplateResponse,
    PlaybookTemplateUpdate,
)
from lokilinux.services.playbook_template_service import PlaybookTemplateService

router = APIRouter()


def _svc(
    db: AsyncSession = Depends(get_db),
    cache: RedisCache = Depends(get_cache),
    nats=Depends(get_nats),
) -> PlaybookTemplateService:
    return PlaybookTemplateService(db, cache, nats)


@router.get("", response_model=list[PlaybookTemplateResponse], dependencies=[Depends(require_plugin_enabled(ANSIBLE_PLUGIN_NAME))])
async def list_templates(
    svc: PlaybookTemplateService = Depends(_svc),
    _: dict = Depends(get_current_user),
) -> list[PlaybookTemplateResponse]:
    rows = await svc.list_templates()
    return [PlaybookTemplateResponse.model_validate(t) for t in rows]


@router.post("", response_model=PlaybookTemplateResponse, status_code=201, dependencies=[Depends(require_plugin_enabled(ANSIBLE_PLUGIN_NAME))])
async def create_template(
    body: PlaybookTemplateCreate,
    svc: PlaybookTemplateService = Depends(_svc),
    current_user: dict = Depends(require_role("ADMIN", "OPERATOR")),
) -> PlaybookTemplateResponse:
    template = await svc.create_template(
        name=body.name,
        playbook_id=body.playbook_id,
        agent_ids=body.agent_ids,
        description=body.description,
        extra_vars=body.extra_vars,
        created_by=safe_user_uuid(current_user),
    )
    return PlaybookTemplateResponse.model_validate(template)


@router.patch("/{template_id}", response_model=PlaybookTemplateResponse, dependencies=[Depends(require_plugin_enabled(ANSIBLE_PLUGIN_NAME))])
async def update_template(
    template_id: UUID,
    body: PlaybookTemplateUpdate,
    svc: PlaybookTemplateService = Depends(_svc),
    _: dict = Depends(require_role("ADMIN", "OPERATOR")),
) -> PlaybookTemplateResponse:
    try:
        template = await svc.update_template(
            template_id,
            name=body.name,
            description=body.description,
            agent_ids=body.agent_ids,
            extra_vars=body.extra_vars,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return PlaybookTemplateResponse.model_validate(template)


@router.delete("/{template_id}", status_code=204, dependencies=[Depends(require_plugin_enabled(ANSIBLE_PLUGIN_NAME))])
async def delete_template(
    template_id: UUID,
    svc: PlaybookTemplateService = Depends(_svc),
    _: dict = Depends(require_role("ADMIN", "OPERATOR")),
) -> None:
    try:
        await svc.delete_template(template_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{template_id}/launch", response_model=JobResponse, status_code=201, dependencies=[Depends(require_plugin_enabled(ANSIBLE_PLUGIN_NAME))])
async def launch_template(
    template_id: UUID,
    body: PlaybookTemplateLaunchRequest,
    svc: PlaybookTemplateService = Depends(_svc),
    current_user: dict = Depends(require_role("ADMIN", "OPERATOR")),
) -> JobResponse:
    try:
        job = await svc.launch_template(
            template_id,
            agent_ids_override=body.agent_ids,
            extra_vars_override=body.extra_vars,
            created_by=safe_user_uuid(current_user),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return JobResponse.model_validate(job)


@router.get("/{template_id}/history", response_model=list[JobResponse], dependencies=[Depends(require_plugin_enabled(ANSIBLE_PLUGIN_NAME))])
async def get_template_history(
    template_id: UUID,
    svc: PlaybookTemplateService = Depends(_svc),
    _: dict = Depends(get_current_user),
) -> list[JobResponse]:
    rows = await svc.get_history(template_id)
    return [JobResponse.model_validate(j) for j in rows]
