"""
LokiLinux — AnsibleRoleService: CRUD for reusable Ansible roles.

Files live in object storage (Object Storage plan) as a single JSON object
per role version — new roles write through StorageService and carry
content_object_id; legacy rows keep reading straight from the `files`
JSONB column (dual-read, no backfill).
"""

import json
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.models.ansible_role import AnsibleRole
from lokilinux.object_storage import ObjectStorage
from lokilinux.services.storage_service import StorageService

_MAX_ROLE_BYTES = 8 * 1024 * 1024  # 8MiB — a role is many small text files, generous ceiling


class AnsibleRoleService:
    def __init__(self, db: AsyncSession, storage: ObjectStorage) -> None:
        self.db = db
        self.storage = storage

    async def list_roles(self, limit: int = 100) -> list[AnsibleRole]:
        rows = (await self.db.execute(
            select(AnsibleRole).order_by(AnsibleRole.name).limit(limit)
        )).scalars().all()
        return rows

    async def _get_or_404(self, role_id: UUID) -> AnsibleRole:
        role = await self.db.get(AnsibleRole, role_id)
        if not role:
            raise ValueError(f"Ansible role {role_id} not found")
        return role

    async def get_role(self, role_id: UUID) -> AnsibleRole:
        return await self._get_or_404(role_id)

    async def resolve_files(self, role: AnsibleRole) -> dict:
        """The role's {path: content} map, regardless of whether it lives in
        the legacy `files` column or object storage."""
        if role.content_object_id is not None:
            _, stream = await StorageService(self.storage, self.db).open_stream(
                role.content_object_id
            )
            body = b"".join([chunk async for chunk in stream])
            return json.loads(body.decode("utf-8"))
        return role.files or {}

    async def _store_files(self, name: str, files: dict, created_by: UUID | None) -> UUID:
        obj = await StorageService(self.storage, self.db).store_bytes(
            json.dumps(files).encode("utf-8"),
            category="automation.role",
            original_filename=f"{name}.json",
            content_type="application/json",
            max_bytes=_MAX_ROLE_BYTES,
            created_by=created_by,
        )
        return obj.id

    async def create_role(
        self,
        name: str,
        files: dict,
        description: str | None = None,
        created_by: UUID | None = None,
    ) -> AnsibleRole:
        content_object_id = await self._store_files(name, files, created_by)
        role = AnsibleRole(
            name=name,
            content_object_id=content_object_id,
            file_count=len(files),
            description=description,
            created_by=created_by,
        )
        self.db.add(role)
        await self.db.commit()
        return role

    async def update_role(
        self,
        role_id: UUID,
        name: str | None = None,
        description: str | None = None,
        files: dict | None = None,
        is_enabled: bool | None = None,
    ) -> AnsibleRole:
        role = await self._get_or_404(role_id)
        if name is not None:
            role.name = name
        if description is not None:
            role.description = description
        if files is not None and files != await self.resolve_files(role):
            role.content_object_id = await self._store_files(
                name or role.name, files, role.created_by
            )
            role.files = None  # new edits always move fully onto object storage
            role.file_count = len(files)
            role.version += 1  # same pattern as Playbook.version
        if is_enabled is not None:
            role.is_enabled = is_enabled
        role.updated_at = datetime.now(timezone.utc)
        await self.db.commit()
        return role

    async def delete_role(self, role_id: UUID) -> None:
        role = await self._get_or_404(role_id)
        await self.db.delete(role)
        await self.db.commit()

    async def snapshot_roles(self, role_ids: list[str]) -> dict:
        """Return {role_name: {path: content}} for the given role ids —
        embedded into Job.parameters at playbook execution time so the run
        is immutable even if roles are edited later (same snapshot rule as
        playbook_content)."""
        if not role_ids:
            return {}
        try:
            ids = [UUID(r) for r in role_ids]
        except ValueError as e:
            raise ValueError(f"Invalid role id in playbook role_ids {role_ids!r}: {e}") from e
        rows = (await self.db.execute(
            select(AnsibleRole).where(
                AnsibleRole.id.in_(ids),
                AnsibleRole.is_enabled.is_(True),
            )
        )).scalars().all()
        return {role.name: await self.resolve_files(role) for role in rows}
