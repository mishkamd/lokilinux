"""
LokiLinux — Ansible Projects router.

Same plugin gate as /playbooks: all routes require the "ansible-automation"
Plugin row to be is_enabled.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.api.v1.routers.playbooks import ANSIBLE_PLUGIN_NAME, require_plugin_enabled
from lokilinux.auth.dependencies import get_current_user, require_role, safe_user_uuid
from lokilinux.dependencies import get_db
from lokilinux.schemas.ansible_project import (
    AnsibleProjectCreate,
    AnsibleProjectResponse,
    AnsibleProjectUpdate,
)
from lokilinux.services.ansible_project_service import AnsibleProjectService

router = APIRouter()


def _svc(db: AsyncSession = Depends(get_db)) -> AnsibleProjectService:
    return AnsibleProjectService(db)


@router.get("", response_model=list[AnsibleProjectResponse], dependencies=[Depends(require_plugin_enabled(ANSIBLE_PLUGIN_NAME))])
async def list_projects(
    svc: AnsibleProjectService = Depends(_svc),
    _: dict = Depends(get_current_user),
) -> list[AnsibleProjectResponse]:
    rows = await svc.list_projects()
    return [AnsibleProjectResponse.model_validate(p) for p in rows]


@router.post("", response_model=AnsibleProjectResponse, status_code=201, dependencies=[Depends(require_plugin_enabled(ANSIBLE_PLUGIN_NAME))])
async def create_project(
    body: AnsibleProjectCreate,
    svc: AnsibleProjectService = Depends(_svc),
    current_user: dict = Depends(require_role("ADMIN", "OPERATOR")),
) -> AnsibleProjectResponse:
    project = await svc.create_project(
        name=body.name,
        description=body.description,
        default_agent_ids=body.default_agent_ids,
        created_by=safe_user_uuid(current_user),
    )
    return AnsibleProjectResponse.model_validate(project)


@router.get("/{project_id}", response_model=AnsibleProjectResponse, dependencies=[Depends(require_plugin_enabled(ANSIBLE_PLUGIN_NAME))])
async def get_project(
    project_id: UUID,
    svc: AnsibleProjectService = Depends(_svc),
    _: dict = Depends(get_current_user),
) -> AnsibleProjectResponse:
    try:
        project = await svc.get_project(project_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return AnsibleProjectResponse.model_validate(project)


@router.patch("/{project_id}", response_model=AnsibleProjectResponse, dependencies=[Depends(require_plugin_enabled(ANSIBLE_PLUGIN_NAME))])
async def update_project(
    project_id: UUID,
    body: AnsibleProjectUpdate,
    svc: AnsibleProjectService = Depends(_svc),
    _: dict = Depends(require_role("ADMIN", "OPERATOR")),
) -> AnsibleProjectResponse:
    try:
        project = await svc.update_project(
            project_id,
            name=body.name,
            description=body.description,
            default_agent_ids=body.default_agent_ids,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return AnsibleProjectResponse.model_validate(project)


@router.delete("/{project_id}", status_code=204, dependencies=[Depends(require_plugin_enabled(ANSIBLE_PLUGIN_NAME))])
async def delete_project(
    project_id: UUID,
    svc: AnsibleProjectService = Depends(_svc),
    _: dict = Depends(require_role("ADMIN", "OPERATOR")),
) -> None:
    try:
        await svc.delete_project(project_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
