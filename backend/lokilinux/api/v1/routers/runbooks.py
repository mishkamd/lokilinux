"""
LokiLinux — Runbooks router: incident_type -> workflow mapping CRUD +
manual execute.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.auth.dependencies import get_current_user, require_role, safe_user_uuid
from lokilinux.dependencies import get_cache, get_db, get_nats
from lokilinux.incidents.timeline import add_entry
from lokilinux.runbooks.models import Runbook
from lokilinux.runbooks.schemas import RunbookCreate, RunbookExecuteRequest, RunbookResponse
from lokilinux.runbooks.service import execute_runbook

router = APIRouter()

_TENANT_ID = "default"


@router.get("", response_model=list[RunbookResponse])
async def list_runbooks(
    db: AsyncSession = Depends(get_db),
    _: dict[str, Any] = Depends(get_current_user),
) -> list[Runbook]:
    rows = (await db.execute(select(Runbook).where(Runbook.tenant_id == _TENANT_ID))).scalars().all()
    return list(rows)


@router.post("", response_model=RunbookResponse, status_code=201)
async def create_runbook(
    payload: RunbookCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict[str, Any] = Depends(require_role("ADMIN", "OPERATOR")),
) -> Runbook:
    runbook = Runbook(
        tenant_id=_TENANT_ID, name=payload.name, incident_type=payload.incident_type,
        workflow_id=payload.workflow_id, trigger_mode=payload.trigger_mode,
        min_severity=payload.min_severity, enabled=payload.enabled,
        created_by=safe_user_uuid(current_user),
    )
    db.add(runbook)
    await db.flush()
    return runbook


@router.patch("/{runbook_id}", response_model=RunbookResponse)
async def update_runbook(
    runbook_id: UUID,
    payload: RunbookCreate,
    db: AsyncSession = Depends(get_db),
    _: dict[str, Any] = Depends(require_role("ADMIN", "OPERATOR")),
) -> Runbook:
    runbook = await db.get(Runbook, runbook_id)
    if runbook is None:
        raise HTTPException(status_code=404, detail="Runbook not found")
    runbook.name = payload.name
    runbook.incident_type = payload.incident_type
    runbook.workflow_id = payload.workflow_id
    runbook.trigger_mode = payload.trigger_mode
    runbook.min_severity = payload.min_severity
    runbook.enabled = payload.enabled
    await db.flush()
    return runbook


@router.delete("/{runbook_id}", status_code=204)
async def delete_runbook(
    runbook_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: dict[str, Any] = Depends(require_role("ADMIN", "OPERATOR")),
) -> None:
    runbook = await db.get(Runbook, runbook_id)
    if runbook is None:
        raise HTTPException(status_code=404, detail="Runbook not found")
    await db.delete(runbook)
    await db.flush()


@router.post("/{runbook_id}/execute")
async def execute(
    runbook_id: UUID,
    payload: RunbookExecuteRequest,
    db: AsyncSession = Depends(get_db),
    cache: Any = Depends(get_cache),
    nats: Any = Depends(get_nats),
    _: dict[str, Any] = Depends(require_role("ADMIN", "OPERATOR")),
) -> dict[str, str]:
    runbook = await db.get(Runbook, runbook_id)
    if runbook is None:
        raise HTTPException(status_code=404, detail="Runbook not found")
    try:
        run = await execute_runbook(db, cache, runbook, nats=nats)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if payload.incident_id is not None:
        await add_entry(
            db, payload.incident_id, "runbook",
            f"manually executed runbook {runbook.name}", payload={"run_id": str(run.id)},
        )
        await db.commit()

    return {"run_id": str(run.id), "status": "started"}
