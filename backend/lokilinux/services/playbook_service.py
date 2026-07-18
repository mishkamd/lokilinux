"""
LokiLinux — PlaybookService: Ansible playbook CRUD + execution as a Job.

Execution runs locally on each target agent (ansible-playbook --connection=local),
not via SSH from a control node — the agent already holds an outbound mTLS
channel, so no inbound SSH exposure is needed. "Target servers" means agents
already registered in this fleet, selected the same way as regular jobs.
"""

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.cache import RedisCache
from lokilinux.models.job import Job
from lokilinux.models.playbook import Playbook
from lokilinux.services.ansible_role_service import AnsibleRoleService
from lokilinux.services.job_service import JobService


class PlaybookService:
    def __init__(self, db: AsyncSession, cache: RedisCache, nats=None) -> None:
        self.db = db
        self.cache = cache
        self.nats = nats

    async def list_playbooks(self, limit: int = 20) -> list[Playbook]:
        rows = (await self.db.execute(
            select(Playbook).order_by(Playbook.created_at.desc()).limit(limit)
        )).scalars().all()
        return rows

    async def _get_or_404(self, playbook_id: UUID) -> Playbook:
        playbook = await self.db.get(Playbook, playbook_id)
        if not playbook:
            raise ValueError(f"Playbook {playbook_id} not found")
        return playbook

    async def get_playbook(self, playbook_id: UUID) -> Playbook:
        return await self._get_or_404(playbook_id)

    async def create_playbook(
        self,
        name: str,
        content: str,
        description: str | None = None,
        default_extra_vars: dict | None = None,
        created_by: UUID | None = None,
        role_ids: list | None = None,
        project_id: UUID | None = None,
    ) -> Playbook:
        playbook = Playbook(
            name=name,
            content=content,
            description=description,
            default_extra_vars=default_extra_vars,
            generated_by="user",
            created_by=created_by,
            role_ids=[str(r) for r in (role_ids or [])],
            project_id=project_id,
        )
        self.db.add(playbook)
        await self.db.commit()
        return playbook

    async def update_playbook(
        self,
        playbook_id: UUID,
        name: str | None = None,
        description: str | None = None,
        content: str | None = None,
        default_extra_vars: dict | None = None,
        is_enabled: bool | None = None,
        role_ids: list | None = None,
        project_id: UUID | None = None,
        clear_project: bool = False,
    ) -> Playbook:
        playbook = await self._get_or_404(playbook_id)
        if name is not None:
            playbook.name = name
        if description is not None:
            playbook.description = description
        if content is not None and content != playbook.content:
            playbook.content = content
            playbook.version += 1  # same pattern as Policy.version
        if default_extra_vars is not None:
            playbook.default_extra_vars = default_extra_vars
        if is_enabled is not None:
            playbook.is_enabled = is_enabled
        if role_ids is not None:
            playbook.role_ids = [str(r) for r in role_ids]
        if clear_project:
            playbook.project_id = None
        elif project_id is not None:
            playbook.project_id = project_id
        playbook.updated_at = datetime.now(timezone.utc)
        await self.db.commit()
        return playbook

    async def delete_playbook(self, playbook_id: UUID) -> None:
        playbook = await self._get_or_404(playbook_id)
        await self.db.delete(playbook)
        await self.db.commit()

    async def execute_playbook(
        self,
        playbook_id: UUID,
        agent_ids: list[UUID],
        extra_vars: dict | None = None,
        created_by: UUID | None = None,
        extra_job_parameters: dict | None = None,
    ) -> Job:
        """Create a job that runs this playbook's *current* content on the
        given agents. Content is snapshotted into Job.parameters at creation
        time (audit-friendly, immutable per run) rather than re-read from
        the playbook row at execution time.

        requires_approval is always True here — fleet-wide Ansible execution
        needs a human approval step (see JobService.approve_job), not an
        opt-in flag callers could forget to set.

        extra_job_parameters lets a caller (e.g. PlaybookTemplateService)
        stamp extra keys into Job.parameters — such as template_id — without
        duplicating the job-creation logic above.
        """
        playbook = await self._get_or_404(playbook_id)
        if not playbook.is_enabled:
            raise ValueError("Playbook is disabled")

        merged_extra_vars = {**(playbook.default_extra_vars or {}), **(extra_vars or {})}

        # Roles referenced by the playbook are snapshotted like the content:
        # the job carries {role_name: {path: content}}, materialized by the
        # agent under <tmpdir>/roles/ next to the playbook.
        roles = await AnsibleRoleService(self.db).snapshot_roles(playbook.role_ids or [])

        job_service = JobService(self.db, self.cache, self.nats)
        job = await job_service.create_job(
            name=f"Ansible: {playbook.name}",
            job_type="ANSIBLE_PLAYBOOK",
            target_servers={"agent_ids": [str(a) for a in agent_ids]},
            parameters={
                "playbook_id": str(playbook.id),
                "playbook_version": playbook.version,
                "playbook_content": playbook.content,
                "extra_vars": merged_extra_vars,
                "roles": roles,
                **(extra_job_parameters or {}),
            },
            created_by=created_by,
            requires_approval=True,
        )
        return job
