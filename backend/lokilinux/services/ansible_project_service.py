"""
LokiLinux — AnsibleProjectService: CRUD for Ansible project grouping.
"""

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.models.ansible_project import AnsibleProject


class AnsibleProjectService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_projects(self, limit: int = 100) -> list[AnsibleProject]:
        rows = (await self.db.execute(
            select(AnsibleProject).order_by(AnsibleProject.name).limit(limit)
        )).scalars().all()
        return rows

    async def _get_or_404(self, project_id: UUID) -> AnsibleProject:
        project = await self.db.get(AnsibleProject, project_id)
        if not project:
            raise ValueError(f"Ansible project {project_id} not found")
        return project

    async def get_project(self, project_id: UUID) -> AnsibleProject:
        return await self._get_or_404(project_id)

    async def create_project(
        self,
        name: str,
        description: str | None = None,
        default_agent_ids: list | None = None,
        created_by: UUID | None = None,
    ) -> AnsibleProject:
        project = AnsibleProject(
            name=name,
            description=description,
            default_agent_ids=[str(a) for a in (default_agent_ids or [])],
            created_by=created_by,
        )
        self.db.add(project)
        await self.db.commit()
        return project

    async def update_project(
        self,
        project_id: UUID,
        name: str | None = None,
        description: str | None = None,
        default_agent_ids: list | None = None,
    ) -> AnsibleProject:
        project = await self._get_or_404(project_id)
        if name is not None:
            project.name = name
        if description is not None:
            project.description = description
        if default_agent_ids is not None:
            project.default_agent_ids = [str(a) for a in default_agent_ids]
        project.updated_at = datetime.now(timezone.utc)
        await self.db.commit()
        return project

    async def delete_project(self, project_id: UUID) -> None:
        project = await self._get_or_404(project_id)
        await self.db.delete(project)
        await self.db.commit()
