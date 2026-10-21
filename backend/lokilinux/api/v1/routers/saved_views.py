"""
LokiLinux — Saved views router (per user).

GET    /account/views?scope=   — list the caller's views (optionally one scope)
POST   /account/views          — create/replace a view by (scope, name)
DELETE /account/views/{id}     — delete one of the caller's views

Every query is scoped to the caller: a view belongs to the user who saved it,
so a second user cannot read or delete it.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.auth.dependencies import get_current_user
from lokilinux.dependencies import get_db
from lokilinux.models.saved_view import SavedView
from lokilinux.schemas.saved_view import SavedViewCreate, SavedViewResponse

router = APIRouter()


def _user_id(user: dict) -> str:
    raw = user.get("id")
    if not raw or raw == "stub":
        raise HTTPException(status_code=401, detail="Unknown user")
    return str(raw)


@router.get("/account/views", response_model=list[SavedViewResponse])
async def list_saved_views(
    scope: str | None = Query(None, max_length=100),
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
) -> list[SavedViewResponse]:
    q = select(SavedView).where(SavedView.user_id == _user_id(user))
    if scope:
        q = q.where(SavedView.scope == scope)
    rows = (await db.execute(q.order_by(SavedView.name))).scalars().all()
    return [SavedViewResponse.model_validate(r) for r in rows]


@router.post("/account/views", response_model=SavedViewResponse, status_code=201)
async def create_saved_view(
    body: SavedViewCreate,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
) -> SavedViewResponse:
    """Create or replace the view with the same (scope, name) for this user."""
    uid = _user_id(user)
    existing = (
        await db.execute(
            select(SavedView).where(
                SavedView.user_id == uid,
                SavedView.scope == body.scope,
                SavedView.name == body.name,
            )
        )
    ).scalar_one_or_none()

    if existing is not None:
        existing.path = body.path
        existing.query = body.query
        await db.commit()
        await db.refresh(existing)
        return SavedViewResponse.model_validate(existing)

    view = SavedView(
        user_id=uid,
        scope=body.scope,
        name=body.name,
        path=body.path,
        query=body.query,
    )
    db.add(view)
    await db.commit()
    await db.refresh(view)
    return SavedViewResponse.model_validate(view)


@router.delete("/account/views/{view_id}", status_code=204)
async def delete_saved_view(
    view_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
) -> None:
    view = (
        await db.execute(
            select(SavedView).where(SavedView.id == view_id, SavedView.user_id == _user_id(user))
        )
    ).scalar_one_or_none()
    if view is None:
        raise HTTPException(status_code=404, detail="View not found")
    await db.delete(view)
    await db.commit()
