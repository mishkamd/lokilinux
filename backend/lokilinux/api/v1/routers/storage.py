"""
LokiLinux — Centralized object storage router (Object Storage plan).

Generic upload/download/list/delete over lokilinux.services.storage_service.
Download defaults to proxying bytes through the API (StreamingResponse) since
RustFS sits on an internal-only network no browser can reach directly;
presigned URLs are opt-in and only returned when S3_PUBLIC_ENDPOINT_URL is
configured (AWS S3 / R2 / Wasabi, or RustFS behind a reverse proxy).
"""

from typing import AsyncIterator
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.auth.dependencies import get_current_user, require_permission, safe_user_uuid
from lokilinux.config import get_settings
from lokilinux.dependencies import get_db, get_storage
from lokilinux.object_storage import ObjectStorage
from lokilinux.schemas.storage import (
    ImportUrlRequest,
    PresignResponse,
    StorageObjectListResponse,
    StorageObjectResponse,
    VerifyResponse,
)
from lokilinux.services.storage_service import CATEGORIES, StorageService

router = APIRouter()


def _actor_name(user: dict) -> str | None:
    return user.get("username") or user.get("email")


@router.post("/objects", response_model=StorageObjectResponse, status_code=201)
async def upload_object(
    file: UploadFile,
    category: str = Query(...),
    db: AsyncSession = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
    current_user: dict = Depends(require_permission("storage.upload")),
) -> StorageObjectResponse:
    if category not in CATEGORIES:
        raise HTTPException(422, f"unknown storage category: {category!r}")
    settings = get_settings()

    async def _chunks() -> AsyncIterator[bytes]:
        while chunk := await file.read(1024 * 1024):
            yield chunk

    obj = await StorageService(storage, db).store_stream(
        _chunks(),
        category=category,
        original_filename=file.filename or "upload",
        content_type=file.content_type or "application/octet-stream",
        max_bytes=settings.s3_max_upload_bytes,
        created_by=safe_user_uuid(current_user),
        actor_name=_actor_name(current_user),
    )
    return StorageObjectResponse.model_validate(obj)


@router.post("/objects/import-url", response_model=StorageObjectResponse, status_code=201)
async def import_object_from_url(
    body: ImportUrlRequest,
    db: AsyncSession = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
    current_user: dict = Depends(require_permission("storage.upload")),
) -> StorageObjectResponse:
    if body.category not in CATEGORIES:
        raise HTTPException(422, f"unknown storage category: {body.category!r}")
    settings = get_settings()
    filename = body.original_filename or body.url.rsplit("/", 1)[-1] or "import"

    async with httpx.AsyncClient(timeout=120.0) as client:
        async with client.stream("GET", body.url) as resp:
            resp.raise_for_status()
            raw_content_type = resp.headers.get("content-type", "application/octet-stream")
            content_type = raw_content_type.split(";")[0]
            obj = await StorageService(storage, db).store_stream(
                resp.aiter_bytes(1024 * 1024),
                category=body.category,
                original_filename=filename,
                content_type=content_type,
                max_bytes=settings.s3_max_upload_bytes,
                created_by=safe_user_uuid(current_user),
                extra_metadata={"source_url": body.url},
                actor_name=_actor_name(current_user),
            )
    return StorageObjectResponse.model_validate(obj)


@router.get("/objects", response_model=StorageObjectListResponse)
async def list_objects(
    category: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
    _: dict = Depends(get_current_user),
) -> StorageObjectListResponse:
    objects = await StorageService(storage, db).list(category=category, limit=limit, offset=offset)
    return StorageObjectListResponse(
        items=[StorageObjectResponse.model_validate(o) for o in objects],
        next_cursor=None,
        total=len(objects),
    )


@router.get("/objects/{object_id}", response_model=StorageObjectResponse)
async def get_object_metadata(
    object_id: UUID,
    db: AsyncSession = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
    _: dict = Depends(get_current_user),
) -> StorageObjectResponse:
    obj = await StorageService(storage, db).get(object_id)
    return StorageObjectResponse.model_validate(obj)


@router.get("/objects/{object_id}/download", response_model=None)
async def download_object(
    object_id: UUID,
    presign: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
    _: dict = Depends(get_current_user),
) -> PresignResponse | StreamingResponse:
    settings = get_settings()
    service = StorageService(storage, db)

    if presign:
        if not settings.s3_public_endpoint_url:
            raise HTTPException(
                409, "presigned URLs are disabled — S3_PUBLIC_ENDPOINT_URL is not configured"
            )
        url = await service.presign(
            object_id, method="GET", expires_in=settings.s3_presigned_url_expiration
        )
        return PresignResponse(url=url, expires_in=settings.s3_presigned_url_expiration)

    obj, stream = await service.open_stream(object_id)
    return StreamingResponse(
        stream,
        media_type=obj.content_type,
        headers={"Content-Disposition": f'attachment; filename="{obj.filename}"'},
    )


@router.post("/objects/{object_id}/verify", response_model=VerifyResponse)
async def verify_object(
    object_id: UUID,
    db: AsyncSession = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
    _: dict = Depends(get_current_user),
) -> VerifyResponse:
    service = StorageService(storage, db)
    obj = await service.get(object_id)
    match = await service.verify(object_id)
    return VerifyResponse(object_id=object_id, sha256_recorded=obj.sha256, sha256_match=match)


@router.delete("/objects/{object_id}", status_code=204)
async def delete_object(
    object_id: UUID,
    db: AsyncSession = Depends(get_db),
    storage: ObjectStorage = Depends(get_storage),
    current_user: dict = Depends(require_permission("storage.delete")),
) -> None:
    await StorageService(storage, db).delete(object_id, actor_name=_actor_name(current_user))
