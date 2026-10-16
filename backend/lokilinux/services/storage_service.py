"""
LokiLinux — Centralized object storage service (Object Storage plan).

The only layer the rest of the application calls to persist a file. Owns
the full transaction: staging the incoming stream, computing its SHA-256,
enforcing size/category rules, uploading to S3, and writing the
storage_objects metadata row — so callers never touch lokilinux.object_storage
or the container filesystem directly.

Staging uses tempfile.SpooledTemporaryFile: below the threshold it never
leaves RAM, above it spills to /tmp, which is tmpfs on every app container
(docker-compose.yml, read_only + tmpfs: [/tmp]) — so nothing here ever
touches a persistent disk.
"""

from __future__ import annotations

import hashlib
import tempfile
from typing import AsyncIterator
from uuid import UUID, uuid4

import structlog
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.models.storage_object import StorageObject
from lokilinux.object_storage import ObjectStorage, sanitize_filename
from lokilinux.services.audit_service import AuditService

logger = structlog.get_logger()

# Single source of truth for storage prefixes — never write a raw prefix
# string at a call site (same rule as nats_topics.py for NATS subjects).
CATEGORIES: dict[str, str] = {
    "compliance.datastream": "compliance/datastreams",
    "compliance.benchmark": "compliance/benchmarks",
    "compliance.report": "compliance/reports",
    "compliance.evidence": "compliance/evidence",
    "security.vulnerability": "security/vulnerabilities",
    "security.artifact": "security/artifacts",
    "incident": "incidents",
    "automation.playbook": "automation/playbooks",
    "automation.role": "automation/roles",
    "workflow": "workflows",
    "upload": "uploads",
    "export": "exports",
    "report": "reports",
    "system": "system",
}

_SPOOL_MAX_BYTES = 8 * 1024 * 1024  # spill to tmpfs above 8MB, matches multipart threshold


class StorageError(HTTPException):
    """Raised for storage-layer failures the caller should surface as a 4xx."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(status_code=status_code, detail=detail)


def _category_prefix(category: str) -> str:
    prefix = CATEGORIES.get(category)
    if prefix is None:
        raise StorageError(422, f"unknown storage category: {category!r}")
    return prefix


def _build_key(category: str, object_id: UUID, filename: str, version: int) -> str:
    prefix = _category_prefix(category)
    return f"{prefix}/{object_id}/v{version}/{filename}"


class StorageService:
    def __init__(self, storage: ObjectStorage, db: AsyncSession) -> None:
        self._storage = storage
        self._db = db

    async def store_stream(
        self,
        source: AsyncIterator[bytes],
        *,
        category: str,
        original_filename: str,
        content_type: str,
        max_bytes: int,
        created_by: UUID | None = None,
        extra_metadata: dict | None = None,
        actor_name: str | None = None,
    ) -> StorageObject:
        """Drains an async byte stream into a spooled tempfile while hashing
        it, enforces max_bytes, then uploads and records metadata. Caller
        owns validating content_type against an allowlist before calling."""
        filename = sanitize_filename(original_filename)
        digest = hashlib.sha256()
        size = 0

        with tempfile.SpooledTemporaryFile(max_size=_SPOOL_MAX_BYTES) as spool:
            async for chunk in source:
                size += len(chunk)
                if size > max_bytes:
                    raise StorageError(413, f"upload exceeds maximum size of {max_bytes} bytes")
                digest.update(chunk)
                spool.write(chunk)
            spool.seek(0)

            object_id = uuid4()
            object_key = _build_key(category, object_id, filename, version=1)
            await self._storage.put_stream(
                object_key,
                spool,
                content_type=content_type,
                metadata={"sha256": digest.hexdigest()},
            )

        obj = StorageObject(
            id=object_id,
            filename=filename,
            original_filename=original_filename,
            content_type=content_type,
            size_bytes=size,
            sha256=digest.hexdigest(),
            storage_provider="s3",
            bucket=self._storage.bucket,
            object_key=object_key,
            version=1,
            category=category,
            metadata_=extra_metadata or {},
            status="AVAILABLE",
            created_by=created_by,
        )
        self._db.add(obj)
        await self._db.flush()

        await AuditService(self._db).log(
            action="storage.uploaded",
            user_id=str(created_by) if created_by else None,
            actor_name=actor_name,
            resource_type="storage_object",
            resource_id=str(obj.id),
            changes={"category": category, "size_bytes": size, "sha256": obj.sha256},
        )
        return obj

    async def store_bytes(
        self,
        data: bytes,
        *,
        category: str,
        original_filename: str,
        content_type: str,
        max_bytes: int,
        created_by: UUID | None = None,
        extra_metadata: dict | None = None,
        actor_name: str | None = None,
    ) -> StorageObject:
        async def _one_chunk() -> AsyncIterator[bytes]:
            yield data

        return await self.store_stream(
            _one_chunk(),
            category=category,
            original_filename=original_filename,
            content_type=content_type,
            max_bytes=max_bytes,
            created_by=created_by,
            extra_metadata=extra_metadata,
            actor_name=actor_name,
        )

    async def get(self, object_id: UUID) -> StorageObject:
        obj = (
            await self._db.execute(select(StorageObject).where(StorageObject.id == object_id))
        ).scalar_one_or_none()
        if obj is None or obj.status == "DELETED":
            raise StorageError(404, "Object not found")
        return obj

    async def open_stream(self, object_id: UUID) -> tuple[StorageObject, AsyncIterator[bytes]]:
        obj = await self.get(object_id)
        stream = await self._storage.get_stream(obj.object_key)
        return obj, stream

    async def presign(self, object_id: UUID, *, method: str, expires_in: int) -> str:
        obj = await self.get(object_id)
        if method == "GET":
            return await self._storage.presign_get(obj.object_key, expires_in=expires_in)
        return await self._storage.presign_put(
            obj.object_key, expires_in=expires_in, content_type=obj.content_type
        )

    async def verify(self, object_id: UUID) -> bool:
        """Recomputes SHA-256 from S3 and compares against the recorded value."""
        obj, stream = await self.open_stream(object_id)
        digest = hashlib.sha256()
        async for chunk in stream:
            digest.update(chunk)
        return digest.hexdigest() == obj.sha256

    async def delete(self, object_id: UUID, *, actor_name: str | None = None) -> None:
        obj = await self.get(object_id)
        await self._storage.delete(obj.object_key)
        obj.status = "DELETED"
        await self._db.flush()
        await AuditService(self._db).log(
            action="storage.deleted",
            actor_name=actor_name,
            resource_type="storage_object",
            resource_id=str(obj.id),
        )

    async def list(
        self, *, category: str | None, status: str = "AVAILABLE", limit: int = 50, offset: int = 0
    ) -> list[StorageObject]:
        stmt = select(StorageObject).where(StorageObject.status == status)
        if category:
            stmt = stmt.where(StorageObject.category == category)
        stmt = stmt.order_by(StorageObject.created_at.desc()).limit(limit).offset(offset)
        return list((await self._db.execute(stmt)).scalars().all())
