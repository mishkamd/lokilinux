"""
LokiLinux — Category/Project router.

GET    /categories        — list all
POST   /categories        — create
DELETE /categories/{id}   — delete (agents referencing it fall back to NULL via ON DELETE SET NULL)
GET    /projects          — list all, optional ?category_id filter
POST   /projects          — create
DELETE /projects/{id}     — delete
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.auth.dependencies import get_current_user, require_role
from lokilinux.dependencies import get_db
from lokilinux.models.category import Category, Project
from lokilinux.schemas.category import (
    CategoryCreate,
    CategoryResponse,
    ProjectCreate,
    ProjectResponse,
)

router = APIRouter()


@router.get("/categories", response_model=list[CategoryResponse])
async def list_categories(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
) -> list[CategoryResponse]:
    rows = (await db.execute(select(Category).order_by(Category.name))).scalars().all()
    return [CategoryResponse.model_validate(c) for c in rows]


@router.post("/categories", response_model=CategoryResponse, status_code=201)
async def create_category(
    body: CategoryCreate,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("ADMIN", "OPERATOR")),
) -> CategoryResponse:
    category = Category(name=body.name)
    db.add(category)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Category already exists")
    await db.refresh(category)
    return CategoryResponse.model_validate(category)


@router.get("/projects", response_model=list[ProjectResponse])
async def list_projects(
    category_id: UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
) -> list[ProjectResponse]:
    q = select(Project).order_by(Project.name)
    if category_id:
        q = q.where(Project.category_id == category_id)
    rows = (await db.execute(q)).scalars().all()
    return [ProjectResponse.model_validate(p) for p in rows]


@router.post("/projects", response_model=ProjectResponse, status_code=201)
async def create_project(
    body: ProjectCreate,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("ADMIN", "OPERATOR")),
) -> ProjectResponse:
    project = Project(name=body.name, category_id=body.category_id)
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return ProjectResponse.model_validate(project)


