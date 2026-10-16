"""
LokiLinux — PlaybookTemplateService: saved (playbook + agents + extra_vars)
launch configs (AWX "Job Template" equivalent), and their execution history.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.cache import RedisCache
from lokilinux.models.job import Job
from lokilinux.models.playbook_template import PlaybookTemplate
from lokilinux.object_storage import ObjectStorage
from lokilinux.services.playbook_service import PlaybookService


class PlaybookTemplateService:
    def __init__(
        self, db: AsyncSession, cache: RedisCache, storage: ObjectStorage, nats=None
    ) -> None:
        self.db = db
        self.cache = cache
        self.storage = storage
        self.nats = nats

    async def list_templates(self, limit: int = 50) -> list[PlaybookTemplate]:
        rows = (await self.db.execute(
            select(PlaybookTemplate).order_by(PlaybookTemplate.created_at.desc()).limit(limit)
        )).scalars().all()
        return rows

    async def _get_or_404(self, template_id: UUID) -> PlaybookTemplate:
        template = await self.db.get(PlaybookTemplate, template_id)
        if not template:
            raise ValueError(f"Job Template {template_id} not found")
        return template

    async def create_template(
        self,
        name: str,
        playbook_id: UUID,
        agent_ids: list[UUID],
        description: str | None = None,
        extra_vars: dict | None = None,
        created_by: UUID | None = None,
    ) -> PlaybookTemplate:
        template = PlaybookTemplate(
            name=name,
            playbook_id=playbook_id,
            agent_ids=[str(a) for a in agent_ids],
            description=description,
            extra_vars=extra_vars,
            created_by=created_by,
        )
        self.db.add(template)
        await self.db.commit()
        return template

    async def update_template(
        self,
        template_id: UUID,
        name: str | None = None,
        description: str | None = None,
        agent_ids: list[UUID] | None = None,
        extra_vars: dict | None = None,
    ) -> PlaybookTemplate:
        template = await self._get_or_404(template_id)
        if name is not None:
            template.name = name
        if description is not None:
            template.description = description
        if agent_ids is not None:
            template.agent_ids = [str(a) for a in agent_ids]
        if extra_vars is not None:
            template.extra_vars = extra_vars
        await self.db.commit()
        return template

    async def delete_template(self, template_id: UUID) -> None:
        template = await self._get_or_404(template_id)
        await self.db.delete(template)
        await self.db.commit()

    async def launch_template(
        self,
        template_id: UUID,
        agent_ids_override: list[UUID] | None = None,
        extra_vars_override: dict | None = None,
        created_by: UUID | None = None,
    ) -> Job:
        """Launch a template: runs the referenced playbook's current content
        against the template's saved agents/extra_vars, unless overridden.
        Stamps template_id into Job.parameters so launches can be listed
        as this template's execution history (see get_history)."""
        template = await self._get_or_404(template_id)

        agent_ids = agent_ids_override if agent_ids_override is not None else [
            UUID(a) for a in template.agent_ids
        ]
        merged_extra_vars = {**(template.extra_vars or {}), **(extra_vars_override or {})}

        pb_service = PlaybookService(self.db, self.cache, self.storage, self.nats)
        job = await pb_service.execute_playbook(
            template.playbook_id,
            agent_ids=agent_ids,
            extra_vars=merged_extra_vars,
            created_by=created_by,
            extra_job_parameters={"template_id": str(template.id)},
        )
        return job

    async def get_history(self, template_id: UUID, limit: int = 20) -> list[Job]:
        """Jobs launched from this template — matched via the template_id
        stamped into Job.parameters at launch time (see launch_template)."""
        rows = (
            await self.db.execute(
                select(Job)
                .where(
                    Job.job_type == "ANSIBLE_PLAYBOOK",
                    Job.parameters["template_id"].astext == str(template_id),
                )
                .order_by(Job.created_at.desc())
                .limit(limit)
            )
        ).scalars().all()
        return rows
