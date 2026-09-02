"""
LokiLinux — Alerts router.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.auth.dependencies import get_current_user, require_role
from lokilinux.dependencies import get_db
from lokilinux.schemas.alert import AlertListResponse, AlertRuleListResponse
from lokilinux.services.alert_service import AlertService

router = APIRouter()


def _svc(db: AsyncSession = Depends(get_db)) -> AlertService:
    return AlertService(db)


@router.get("", response_model=AlertListResponse)
async def list_alerts(
    status: str | None = None,
    severity: str | None = None,
    limit: int = Query(20, le=100),
    svc: AlertService = Depends(_svc),
    _user: dict = Depends(get_current_user),
) -> dict:
    return await svc.list_alerts(status, severity, limit)


@router.post("/{alert_id}/acknowledge")
async def acknowledge_alert(
    alert_id: str,
    svc: AlertService = Depends(_svc),
    current_user: dict = Depends(require_role("ADMIN", "OPERATOR")),
) -> dict:
    try:
        alert = await svc.acknowledge(UUID(alert_id), current_user["id"])
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"id": str(alert.id), "status": alert.status}


@router.post("/{alert_id}/resolve")
async def resolve_alert(
    alert_id: str,
    svc: AlertService = Depends(_svc),
    current_user: dict = Depends(require_role("ADMIN", "OPERATOR")),
) -> dict:
    try:
        alert = await svc.resolve(UUID(alert_id), current_user.get("id"))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"id": str(alert.id), "status": alert.status}


@router.get("/rules", response_model=AlertRuleListResponse)
async def list_alert_rules(
    svc: AlertService = Depends(_svc),
    _user: dict = Depends(get_current_user),
) -> dict:
    return await svc.list_rules()
