"""
LokiLinux — WorkflowService: CRUD, versioning, publish for the Workflow Engine.

Mirrors BaselineService's DRAFT -> PUBLISHED lifecycle (services/baseline_service.py)
— a version is immutable once PUBLISHED, and publish is the only transition
that changes which version is "current" for a workflow. Unlike Baseline there
is no APPROVED intermediate state in Phase 1 (no-self-approval enforcement on
publish lands in Phase 11, plan §14) — DRAFT publishes straight to PUBLISHED,
gated only on the compiler reporting the YAML valid.

workflows.slug is exactly the YAML document's metadata.name (already
constrained to the same ^[a-z0-9-]{3,64}$ shape) — one identifier, not two
that could drift apart. workflows.name is the separate human display label
supplied at create time.
"""

from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.models.workflow import Workflow, WorkflowAudit, WorkflowVersion
from lokilinux.schemas.workflow import ValidationResult
from lokilinux.services.policy_service import compute_next_run_at
from lokilinux.services.workflow_compiler import compile_workflow, compute_content_hash


def _validation_error(result: ValidationResult) -> HTTPException:
    return HTTPException(status_code=422, detail={"errors": [e.model_dump() for e in result.errors]})


class WorkflowService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def validate(self, yaml_source: str) -> ValidationResult:
        _doc, _graph, result = compile_workflow(yaml_source)
        return result

    async def _get_workflow(self, workflow_id: UUID) -> Workflow:
        row = (await self.db.execute(select(Workflow).where(Workflow.id == workflow_id))).scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="Workflow not found")
        return row

    async def _get_version(self, workflow_id: UUID, version_id: UUID) -> WorkflowVersion:
        row = (await self.db.execute(
            select(WorkflowVersion).where(WorkflowVersion.id == version_id, WorkflowVersion.workflow_id == workflow_id)
        )).scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="Workflow version not found")
        return row

    async def create_workflow(self, name: str, yaml_source: str, created_by: UUID | None) -> Workflow:
        doc, graph, result = compile_workflow(yaml_source)
        if not result.valid:
            raise _validation_error(result)
        assert doc is not None and graph is not None  # result.valid guarantees both

        existing = (await self.db.execute(select(Workflow).where(Workflow.slug == doc.metadata.name))).scalar_one_or_none()
        if existing is not None:
            raise HTTPException(status_code=409, detail=f"A workflow named '{doc.metadata.name}' already exists")

        workflow = Workflow(
            name=name, slug=doc.metadata.name, description=doc.metadata.description,
            severity=doc.metadata.severity, tags=doc.metadata.tags, created_by=created_by,
        )
        self.db.add(workflow)
        await self.db.flush()  # populate workflow.id before the version row references it

        version = WorkflowVersion(
            workflow_id=workflow.id, version=1, yaml_source=yaml_source,
            graph=graph.model_dump(mode="json", by_alias=True), content_hash=compute_content_hash(yaml_source),
            status="DRAFT", created_by=created_by,
        )
        self.db.add(version)

        self.db.add(WorkflowAudit(
            workflow_id=workflow.id, changed_by=created_by, change_type="CREATE",
            new_value={"version": 1, "slug": doc.metadata.name},
        ))
        await self.db.commit()
        return workflow

    async def create_version(self, workflow_id: UUID, yaml_source: str, created_by: UUID | None) -> WorkflowVersion:
        await self._get_workflow(workflow_id)  # 404 if missing
        _doc, graph, result = compile_workflow(yaml_source)
        if not result.valid:
            raise _validation_error(result)
        assert graph is not None

        max_version = (await self.db.execute(
            select(func.max(WorkflowVersion.version)).where(WorkflowVersion.workflow_id == workflow_id)
        )).scalar_one()

        version = WorkflowVersion(
            workflow_id=workflow_id, version=(max_version or 0) + 1, yaml_source=yaml_source,
            graph=graph.model_dump(mode="json", by_alias=True), content_hash=compute_content_hash(yaml_source),
            status="DRAFT", created_by=created_by,
        )
        self.db.add(version)
        self.db.add(WorkflowAudit(
            workflow_id=workflow_id, changed_by=created_by, change_type="CREATE_VERSION",
            new_value={"version": version.version},
        ))
        await self.db.commit()
        return version

    async def update_draft(
        self, workflow_id: UUID, version_id: UUID, yaml_source: str, base_content_hash: str | None,
    ) -> WorkflowVersion:
        version = await self._get_version(workflow_id, version_id)
        if version.status != "DRAFT":
            raise HTTPException(status_code=409, detail=f"Cannot edit a {version.status} version — create a new one instead")
        if base_content_hash is not None and base_content_hash != version.content_hash:
            raise HTTPException(
                status_code=409,
                detail="This version was changed since you loaded it — reload and reapply your edits",
            )

        _doc, graph, result = compile_workflow(yaml_source)
        if not result.valid:
            raise _validation_error(result)
        assert graph is not None

        version.yaml_source = yaml_source
        version.graph = graph.model_dump(mode="json", by_alias=True)
        version.content_hash = compute_content_hash(yaml_source)
        await self.db.commit()
        return version

    async def publish_version(self, workflow_id: UUID, version_id: UUID, actor: UUID | None) -> WorkflowVersion:
        version = await self._get_version(workflow_id, version_id)
        if version.status != "DRAFT":
            raise HTTPException(status_code=409, detail=f"Cannot publish from status {version.status}")

        # Re-validate at publish time, not just trusting the last edit's
        # result — the two requests are never guaranteed adjacent in time,
        # and this is the last gate before a workflow can ever run (plan
        # §13 Level 3: "Un DRAFT invalid nu poate deveni PUBLISHED").
        _doc, _graph, result = compile_workflow(version.yaml_source)
        if not result.valid:
            raise _validation_error(result)

        workflow = await self._get_workflow(workflow_id)

        # Exactly one PUBLISHED version per workflow — archive the outgoing
        # one, never delete it (history stays intact for past runs that
        # reference it — plan §15 versioning).
        if workflow.current_version_id is not None:
            current = (await self.db.execute(
                select(WorkflowVersion).where(WorkflowVersion.id == workflow.current_version_id)
            )).scalar_one_or_none()
            if current is not None and current.status == "PUBLISHED":
                current.status = "ARCHIVED"

        version.status = "PUBLISHED"
        version.published_at = datetime.now(timezone.utc)
        workflow.current_version_id = version.id

        self.db.add(WorkflowAudit(
            workflow_id=workflow_id, changed_by=actor, change_type="PUBLISH",
            new_value={"version_id": str(version_id), "version": version.version},
        ))
        await self.db.commit()
        return version

    async def update_metadata(self, workflow_id: UUID, changes: dict) -> Workflow:
        """Same cron-on-PATCH handling as PolicyUpdate (routers/policies.py's
        update_policy) — mutating trigger_type/cron_expr must recompute
        next_run_at, or WorkflowSchedulerWorker's `next_run_at <= now()`
        query silently never picks the workflow up."""
        workflow = await self._get_workflow(workflow_id)
        for field, value in changes.items():
            setattr(workflow, field, value)

        if "trigger_type" in changes or "cron_expr" in changes:
            if workflow.trigger_type == "SCHEDULE":
                if not workflow.cron_expr:
                    raise HTTPException(status_code=422, detail="cron_expr is required when trigger_type is SCHEDULE")
                try:
                    workflow.next_run_at = compute_next_run_at(workflow.cron_expr)
                except Exception as exc:
                    raise HTTPException(status_code=422, detail=f"invalid cron_expr: {exc}") from exc
            else:
                workflow.next_run_at = None

        await self.db.commit()
        return workflow

    async def delete_workflow(self, workflow_id: UUID) -> None:
        workflow = await self._get_workflow(workflow_id)
        await self.db.delete(workflow)
        await self.db.commit()
