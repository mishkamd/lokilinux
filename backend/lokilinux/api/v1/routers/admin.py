"""
LokiLinux — Admin router: user management, settings, audit log.
"""

from typing import Optional

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.auth.dependencies import require_role
from lokilinux.cache import RedisCache
from lokilinux.config import get_settings
from lokilinux.dependencies import get_cache, get_db
from lokilinux.models.audit import Setting
from lokilinux.services import cert_revocation
from lokilinux.services.audit_service import AuditService
from lokilinux.settings_schema import PUBLIC_GROUPS, PUBLIC_KEYS, get_all_settings, update_settings

router = APIRouter()

_AGENT_KEYS = ("agent.download_base", "agent.version", "agent.platform_url")


# ── Agent config ──────────────────────────────────────────────────────────────

@router.get("/agent-config")
async def get_agent_config(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("ADMIN", "OPERATOR")),
) -> dict:
    rows = (await db.execute(
        select(Setting).where(Setting.key.in_(_AGENT_KEYS))
    )).scalars().all()
    cfg = {r.key: r.value for r in rows}
    return {
        "download_base": cfg.get("agent.download_base", ""),
        "version": cfg.get("agent.version", "0.1.0"),
        "platform_url": cfg.get("agent.platform_url", ""),
    }


class AgentConfigUpdate(BaseModel):
    download_base: str = ""
    version: str = "0.1.0"
    platform_url: str = ""


@router.put("/agent-config")
async def update_agent_config(
    body: AgentConfigUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("ADMIN")),
) -> dict:
    updates = {
        "agent.download_base": body.download_base,
        "agent.version": body.version,
        "agent.platform_url": body.platform_url,
    }
    for key, value in updates.items():
        stmt = pg_insert(Setting).values(key=key, value=value).on_conflict_do_update(
            index_elements=["key"], set_={"value": value}
        )
        await db.execute(stmt)
    await db.commit()
    await AuditService(db).log(
        action="admin.agent_config_updated",
        user_id=current_user.get("id"),
        actor_name=current_user.get("username") or current_user.get("email"),
        resource_type="setting",
        changes=updates,
    )
    return {"status": "ok"}


# ── User management (proxied to Better Auth admin API) ────────────────────────

@router.get("/users")
async def list_users(
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(require_role("ADMIN")),
    authorization: Optional[str] = Header(None, alias="Authorization"),
) -> dict:
    settings = get_settings()
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{settings.better_auth_url}/api/auth/admin/list-users",
                headers={"Authorization": authorization or ""},
                params={"limit": limit, "offset": offset},
            )
    except httpx.RequestError:
        return {"items": [], "total": 0}
    if resp.status_code != 200:
        return {"items": [], "total": 0}
    data = resp.json()
    return {"items": data.get("users", []), "total": data.get("total", 0)}


class CreateUserRequest(BaseModel):
    email: str
    username: str
    password: str
    role: str = "VIEWER"


@router.post("/users")
async def create_user(
    body: CreateUserRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("ADMIN")),
    authorization: Optional[str] = Header(None, alias="Authorization"),
) -> dict:
    settings = get_settings()
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{settings.better_auth_url}/api/auth/admin/create-user",
                headers={"Authorization": authorization or "", "Content-Type": "application/json"},
                json={
                    "email": body.email,
                    "name": body.username,
                    "password": body.password,
                    "role": body.role.lower(),
                },
            )
    except httpx.RequestError as exc:
        raise HTTPException(status_code=503, detail=f"Auth provider unreachable: {exc}") from exc
    if resp.status_code not in (200, 201):
        raise HTTPException(status_code=502, detail="Failed to create user in auth provider")

    user_data = resp.json()
    await AuditService(db).log(
        action="admin.user_created",
        user_id=current_user.get("id"),
        actor_name=current_user.get("username") or current_user.get("email"),
        resource_type="user",
        resource_id=user_data.get("user", {}).get("id"),
        changes={"email": body.email, "role": body.role.upper()},
    )
    return user_data


@router.post("/users/{user_id}/role")
async def assign_role(
    user_id: str,
    role: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("ADMIN")),
    authorization: Optional[str] = Header(None, alias="Authorization"),
) -> dict:
    valid_roles = {"ADMIN", "OPERATOR", "VIEWER", "AUDITOR"}
    if role.upper() not in valid_roles:
        raise HTTPException(status_code=400, detail=f"Invalid role. Must be one of: {valid_roles}")

    settings = get_settings()
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{settings.better_auth_url}/api/auth/admin/set-role",
            headers={"Authorization": authorization or "", "Content-Type": "application/json"},
            json={"userId": user_id, "role": role.lower()},
        )
    if resp.status_code not in (200, 201):
        raise HTTPException(status_code=502, detail="Failed to update role in auth provider")

    await AuditService(db).log(
        action="user.role_assigned",
        user_id=current_user.get("id"),
        actor_name=current_user.get("username") or current_user.get("email"),
        resource_type="user",
        resource_id=user_id,
        changes={"role": role.upper()},
    )
    return {"status": "assigned", "user_id": user_id, "role": role.upper()}


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("ADMIN")),
    authorization: Optional[str] = Header(None, alias="Authorization"),
) -> dict:
    if user_id == current_user.get("id"):
        raise HTTPException(status_code=400, detail="Cannot delete your own account")

    settings = get_settings()
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{settings.better_auth_url}/api/auth/admin/remove-user",
            headers={"Authorization": authorization or "", "Content-Type": "application/json"},
            json={"userId": user_id},
        )
    if resp.status_code not in (200, 201):
        raise HTTPException(status_code=502, detail="Failed to delete user in auth provider")

    await AuditService(db).log(
        action="admin.user_deleted",
        user_id=current_user.get("id"),
        actor_name=current_user.get("username") or current_user.get("email"),
        resource_type="user",
        resource_id=user_id,
    )
    return {"status": "deleted"}


# ── Platform settings (LDAP, 2FA, notifications, fleet, retention, branding…) ──

@router.get("/settings")
async def get_platform_settings(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("ADMIN", "OPERATOR")),
) -> dict:
    return await get_all_settings(db)


@router.get("/settings/public")
async def get_public_settings(db: AsyncSession = Depends(get_db)) -> dict:
    """Unauthenticated subset — branding for the login page, require_2fa for the client guard."""
    all_settings = await get_all_settings(db, groups=PUBLIC_GROUPS | {k.split(".")[0] for k in PUBLIC_KEYS})
    public: dict = {g: all_settings[g] for g in PUBLIC_GROUPS if g in all_settings}
    for full_key in PUBLIC_KEYS:
        group, _, key = full_key.partition(".")
        public.setdefault(group, {})[key] = all_settings.get(group, {}).get(key)
    return public


@router.put("/settings")
async def put_platform_settings(
    payload: dict[str, dict],
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("ADMIN")),
) -> dict:
    changes = await update_settings(db, payload)
    if changes:
        await AuditService(db).log(
            action="admin.settings_updated",
            user_id=current_user.get("id"),
            actor_name=current_user.get("username") or current_user.get("email"),
            resource_type="setting",
            changes=changes,
        )
    return {"status": "ok"}


# ── Audit log ─────────────────────────────────────────────────────────────────

@router.get("/audit")
async def list_audit_logs(
    limit: int = Query(50, le=200),
    cursor: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(require_role("ADMIN", "AUDITOR")),
) -> dict:
    return await AuditService(db).list_logs(limit, cursor)


# ── Certificate revocation (P11 CRL-lite) ─────────────────────────────────────

@router.post("/certificates/{serial}/revoke")
async def revoke_certificate(
    serial: str,
    db: AsyncSession = Depends(get_db),
    cache: RedisCache = Depends(get_cache),
    current_user: dict = Depends(require_role("ADMIN")),
) -> dict:
    """Adds a certificate serial to the Redis revocation set. Agents presenting
    it are rejected at the next mTLS connection attempt (fail-closed)."""
    try:
        norm = await cert_revocation.revoke(cache, serial)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await AuditService(db).log(
        action="certificate.revoked",
        actor_name=current_user.get("username") or current_user.get("email"),
        resource_type="certificate",
        resource_id=norm,
        changes={"serial": norm},
        status="success",
    )
    return {"serial": norm, "revoked": True}


@router.post("/certificates/{serial}/unrevoke")
async def unrevoke_certificate(
    serial: str,
    db: AsyncSession = Depends(get_db),
    cache: RedisCache = Depends(get_cache),
    current_user: dict = Depends(require_role("ADMIN")),
) -> dict:
    try:
        was_present = await cert_revocation.unrevoke(cache, serial)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await AuditService(db).log(
        action="certificate.unrevoked",
        actor_name=current_user.get("username") or current_user.get("email"),
        resource_type="certificate",
        resource_id=serial.lower().removeprefix("0x"),
        changes={"was_present": was_present},
        status="success",
    )
    return {"serial": serial.lower().removeprefix("0x"), "revoked": False}


@router.get("/certificates/revoked")
async def list_revoked_certificates(
    _: dict = Depends(require_role("ADMIN")),
    cache: RedisCache = Depends(get_cache),
) -> dict:
    """Admin-only listing; serials are not exposed through any non-admin API."""
    return {"revoked": await cert_revocation.list_revoked(cache)}
