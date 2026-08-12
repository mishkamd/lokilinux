"""
LokiLinux — Ansible Roles router.

Same plugin gate as /playbooks: all routes require the "ansible-automation"
Plugin row to be is_enabled.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.api.v1.routers.playbooks import ANSIBLE_PLUGIN_NAME, require_plugin_enabled
from lokilinux.auth.dependencies import get_current_user, require_role, safe_user_uuid
from lokilinux.dependencies import get_db
from lokilinux.schemas.ansible_role import (
    AnsibleRoleCreate,
    AnsibleRoleResponse,
    AnsibleRoleUpdate,
)
from lokilinux.services.ansible_role_service import AnsibleRoleService

router = APIRouter()


def _svc(db: AsyncSession = Depends(get_db)) -> AnsibleRoleService:
    return AnsibleRoleService(db)


@router.get("", response_model=list[AnsibleRoleResponse], dependencies=[Depends(require_plugin_enabled(ANSIBLE_PLUGIN_NAME))])
async def list_roles(
    svc: AnsibleRoleService = Depends(_svc),
    _: dict = Depends(get_current_user),
) -> list[AnsibleRoleResponse]:
    rows = await svc.list_roles()
    return [AnsibleRoleResponse.model_validate(r) for r in rows]


@router.post("", response_model=AnsibleRoleResponse, status_code=201, dependencies=[Depends(require_plugin_enabled(ANSIBLE_PLUGIN_NAME))])
async def create_role(
    body: AnsibleRoleCreate,
    svc: AnsibleRoleService = Depends(_svc),
    current_user: dict = Depends(require_role("ADMIN", "OPERATOR")),
) -> AnsibleRoleResponse:
    role = await svc.create_role(
        name=body.name,
        files=body.files,
        description=body.description,
        created_by=safe_user_uuid(current_user),
    )
    return AnsibleRoleResponse.model_validate(role)


@router.get("/{role_id}", response_model=AnsibleRoleResponse, dependencies=[Depends(require_plugin_enabled(ANSIBLE_PLUGIN_NAME))])
async def get_role(
    role_id: UUID,
    svc: AnsibleRoleService = Depends(_svc),
    _: dict = Depends(get_current_user),
) -> AnsibleRoleResponse:
    try:
        role = await svc.get_role(role_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return AnsibleRoleResponse.model_validate(role)


@router.patch("/{role_id}", response_model=AnsibleRoleResponse, dependencies=[Depends(require_plugin_enabled(ANSIBLE_PLUGIN_NAME))])
async def update_role(
    role_id: UUID,
    body: AnsibleRoleUpdate,
    svc: AnsibleRoleService = Depends(_svc),
    _: dict = Depends(require_role("ADMIN", "OPERATOR")),
) -> AnsibleRoleResponse:
    try:
        role = await svc.update_role(
            role_id,
            name=body.name,
            description=body.description,
            files=body.files,
            is_enabled=body.is_enabled,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return AnsibleRoleResponse.model_validate(role)


@router.delete("/{role_id}", status_code=204, dependencies=[Depends(require_plugin_enabled(ANSIBLE_PLUGIN_NAME))])
async def delete_role(
    role_id: UUID,
    svc: AnsibleRoleService = Depends(_svc),
    _: dict = Depends(require_role("ADMIN", "OPERATOR")),
) -> None:
    try:
        await svc.delete_role(role_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
