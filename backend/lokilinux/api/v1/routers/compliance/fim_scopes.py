"""
LokiLinux — Compliance: File Integrity scope router.

CRUD over fim_scopes (GLOBAL default + AGENT overrides) — see
services/fim_scope_service.py for the resolution/signing logic and why this
is a separate channel from file_integrity_ignores. Mirrors baselines.py's
convention: get_current_user for reads, require_role for mutations.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.auth.dependencies import get_current_user, require_role, safe_user_uuid
from lokilinux.dependencies import get_db
from lokilinux.models.agent import Agent
from lokilinux.models.file_integrity import FIMScope
from lokilinux.schemas.file_integrity import (
    FIMAgentScopeResponse,
    FIMScopeResponse,
    FIMScopeUpdate,
    FIMScopesOverview,
)
from lokilinux.services import fim_scope_service

router = APIRouter()


@router.get("/fim-scopes", response_model=FIMScopesOverview)
async def get_fim_scopes(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
) -> FIMScopesOverview:
    global_row = await fim_scope_service.get_global_scope(db)
    if global_row is None:
        raise HTTPException(500, "no GLOBAL fim_scopes row — migration 044 seed missing")

    agent_rows = (
        await db.execute(
            select(FIMScope, Agent.hostname)
            .outerjoin(Agent, Agent.id == FIMScope.agent_id)
            .where(FIMScope.scope_type == "AGENT")
            .order_by(FIMScope.updated_at.desc())
        )
    ).all()

    return FIMScopesOverview(
        global_scope=FIMScopeResponse.model_validate(global_row),
        agents=[
            FIMAgentScopeResponse.model_validate(row).model_copy(update={"hostname": hostname})
            for row, hostname in agent_rows
        ],
    )


@router.put("/fim-scopes", response_model=FIMScopeResponse)
async def update_global_fim_scope(
    body: FIMScopeUpdate,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_role("ADMIN", "OPERATOR")),
) -> FIMScopeResponse:
    try:
        row = await fim_scope_service.upsert_global_scope(
            db, body.watch_paths, body.ignore_paths, safe_user_uuid(user)
        )
    except fim_scope_service.FIMScopeValidationError as exc:
        raise HTTPException(422, str(exc)) from exc
    await db.commit()
    return FIMScopeResponse.model_validate(row)


@router.put("/fim-scopes/{agent_id}", response_model=FIMScopeResponse)
async def update_agent_fim_scope(
    agent_id: UUID,
    body: FIMScopeUpdate,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_role("ADMIN", "OPERATOR")),
) -> FIMScopeResponse:
    try:
        row = await fim_scope_service.upsert_agent_scope(
            db, agent_id, body.watch_paths, body.ignore_paths, safe_user_uuid(user)
        )
    except fim_scope_service.FIMScopeValidationError as exc:
        raise HTTPException(422, str(exc)) from exc
    await db.commit()
    return FIMScopeResponse.model_validate(row)


@router.delete("/fim-scopes/{agent_id}", status_code=204)
async def delete_agent_fim_scope(
    agent_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("ADMIN", "OPERATOR")),
) -> None:
    deleted = await fim_scope_service.delete_agent_scope(db, agent_id)
    await db.commit()
    if not deleted:
        raise HTTPException(404, "no per-agent override for this agent")
