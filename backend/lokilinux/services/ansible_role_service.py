"""
LokiLinux — AnsibleRoleService: CRUD for reusable Ansible roles.
"""

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.models.ansible_role import AnsibleRole


class AnsibleRoleService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

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

    async def create_role(
        self,
        name: str,
        files: dict,
        description: str | None = None,
        created_by: UUID | None = None,
    ) -> AnsibleRole:
        role = AnsibleRole(name=name, files=files, description=description, created_by=created_by)
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
        if files is not None and files != role.files:
            role.files = files
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
        return {role.name: role.files for role in rows}
