"""Unit tests for require_permission() / auth.permissions.PERMISSIONS —
Enterprise Compliance plan U9. Parametrized role x permission matrix
(Task 4) plus the denial-is-audited behavior (Task 2) that distinguishes
require_permission from the plain require_role it's layered alongside.
"""

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from lokilinux.auth.dependencies import require_permission
from lokilinux.auth.permissions import PERMISSIONS
from lokilinux.models.audit import AuditLog

ALL_ROLES = ("ADMIN", "MANAGER", "OPERATOR", "VIEWER", "AUDITOR")


@pytest.mark.asyncio
@pytest.mark.parametrize("permission", sorted(PERMISSIONS))
@pytest.mark.parametrize("role", ALL_ROLES)
async def test_permission_matrix(permission, role, db_session):
    """For every (permission, role) pair: ADMIN always passes; any other
    role passes iff it's in PERMISSIONS[permission], denies otherwise —
    the exact role sets each route granted via require_role(...) before
    this migration (verified route-by-route, see permissions.py docstring).
    Denials write an audit row (AuditService), so this needs a real db
    session even though the matrix isn't asserting on that row itself
    (test_denial_is_audited below does)."""
    check = require_permission(permission)
    user = {"id": str(uuid.uuid4()), "role": role}
    allowed = role == "ADMIN" or role in PERMISSIONS[permission]

    if allowed:
        assert await check(user=user, db=db_session) == user
    else:
        with pytest.raises(HTTPException) as exc_info:
            await check(user=user, db=db_session)
        assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_denial_is_audited(db_session):
    """A 403 from require_permission is a security event, not just a UX
    one — unlike require_role's plain reject, it must leave an audit trail
    (plan U9 Task 2)."""
    check = require_permission("compliance.policies.archive")  # ADMIN-only
    user = {"id": "u-viewer", "role": "VIEWER", "email": "viewer@example.com"}

    with pytest.raises(HTTPException) as exc_info:
        await check(user=user, db=db_session)
    assert exc_info.value.status_code == 403
    assert "compliance.policies.archive" in exc_info.value.detail

    row = (
        await db_session.execute(select(AuditLog).where(AuditLog.action == "rbac.denied"))
    ).scalar_one()
    assert row.user_id == "u-viewer"
    assert row.actor_name == "viewer@example.com"
    assert row.resource_type == "permission"
    assert row.resource_id == "compliance.policies.archive"
    assert row.changes == {"role": "VIEWER"}
    assert row.status == "failure"


@pytest.mark.asyncio
async def test_grant_never_writes_audit_row(db_session):
    """The audit write is denial-only — a permitted call must not add
    log noise on every successful request."""
    check = require_permission("compliance.policies.archive")
    admin = {"id": "u-admin", "role": "ADMIN"}

    assert await check(user=admin, db=db_session) == admin

    rows = (await db_session.execute(select(AuditLog))).scalars().all()
    assert rows == []
