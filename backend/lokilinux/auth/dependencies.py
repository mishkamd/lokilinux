"""
LokiLinux — Auth dependencies.

get_current_user: re-exported from jwks_validator (RS256 via Better Auth JWKS).
require_role: factory that enforces role-based access on top of get_current_user.
"""

from typing import Any
from uuid import UUID

from fastapi import Depends, HTTPException

from .jwks_validator import get_current_user

__all__ = ["get_current_user", "require_role", "safe_user_uuid"]


def safe_user_uuid(current_user: dict[str, Any]) -> UUID | None:
    """Better Auth's `id` (nanoid) doesn't always parse as UUID — degrade to None.

    ponytail: model inconsistency (created_by/acknowledged_by columns are UUID);
    unify to String(255) in a future migration instead of resolving via
    user_profiles on every write.
    """
    raw = current_user.get("id")
    if not raw or raw == "stub":
        return None
    try:
        return UUID(raw)
    except ValueError:
        return None


def require_role(*roles: str):  # type: ignore[return]
    """Dependency factory. ADMIN always passes; other roles must be in *roles."""
    async def _check(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
        user_role = user.get("role", "VIEWER")
        if user_role != "ADMIN" and user_role not in roles:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return user
    return _check
