"""
LokiLinux — Policy → Workflow importer (migration plan Partea I §15, Phase 9
stage B). One-way, idempotent: re-importing an already-migrated policy
returns the existing workflow rather than creating a duplicate.

Deliberately narrow. Workflow's own engine (workflow_engine.py's
_EXECUTABLE_TYPES) only dispatches a Job for `command`/`validation`/`ansible`
steps — `package` compiles and displays fine but nothing runs it yet (Phase
10, needs a native agent module), and there is no workflow step type at all
for the other Job types a Policy can carry (SECURITY_PATCH, INVENTORY_SCAN,
CVE_SCAN, REMEDIATION, COMPLIANCE_REMEDIATE, PLUGIN_INSTALL). Importing one
of those today would produce a workflow that silently behaves differently
from the policy it claims to replace — worse than not importing it at all.
PolicyMigrationError names exactly which policies aren't ready, rather than
the importer guessing.

`execution.requires_approval` on a Policy has no per-step equivalent on a
WorkflowStep (workflow_engine.py's _dispatch_step always dispatches with
requires_approval=False — the workflow's own `approval` node type IS the
human gate). A requires_approval policy is therefore imported as TWO steps
(approval -> the action), not one — this is exactly why `approval` exists as
a first-class step type, not a deviation from "one step" so much as its
natural extension once a human gate is part of what's being represented.
"""

import re
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.models.policy import Policy
from lokilinux.models.workflow import Workflow, WorkflowVersion
from lokilinux.object_storage import ObjectStorage
from lokilinux.schemas.workflow import (
    WorkflowDocument,
    WorkflowEdge,
    WorkflowMetadata,
    WorkflowSpec,
    WorkflowStep,
    WorkflowTargets,
)
from lokilinux.services.workflow_compiler import serialize_document
from lokilinux.services.workflow_service import WorkflowService

_VALID_SEVERITIES = ("LOW", "MEDIUM", "HIGH", "CRITICAL")

# JobService job_type -> the workflow step type whose _dispatch_step
# (workflow_engine.py) produces that SAME job_type against the SAME
# target_servers/parameters shape run_policy already uses.
_JOB_TYPE_TO_STEP_TYPE = {
    "CUSTOM_COMMAND": "command",
    "ANSIBLE_PLAYBOOK": "ansible",
}


class PolicyMigrationError(Exception):
    """A Policy can't be represented as an equivalent Workflow yet — an
    unsupported action type, unresolvable targets, or an invalid severity.
    Never silently produced a workflow that would diverge from its source."""


def _slugify(name: str, policy_id: UUID) -> str:
    base = re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-") or "policy"
    suffix = str(policy_id)[:8]
    # metadata.name is capped at 64 chars (schemas/workflow.py's
    # _WORKFLOW_NAME_RE) — truncate the human part, never the id suffix that
    # keeps two similarly-named policies from colliding.
    return f"{base[:64 - len(suffix) - 1]}-{suffix}".strip("-")


def _step_config(step_type: str, params: dict) -> dict:
    if step_type == "command":
        return {"command": params.get("command", "")}
    return {"playbook_id": params.get("playbook_id"), "extra_vars": params.get("extra_vars") or {}}


def _build_document(policy: Policy) -> WorkflowDocument:
    if not policy.actions:
        raise PolicyMigrationError(f"Policy '{policy.name}' has no actions — nothing to migrate")
    action = policy.actions[0]
    job_type = action.get("type")
    step_type = _JOB_TYPE_TO_STEP_TYPE.get(job_type)
    if step_type is None:
        raise PolicyMigrationError(
            f"Policy '{policy.name}' uses job_type '{job_type}', which has no equivalent executable workflow step type yet",
        )

    targets_raw = policy.target_servers or {}
    try:
        targets = WorkflowTargets.model_validate(targets_raw)
    except Exception as exc:
        raise PolicyMigrationError(f"Policy '{policy.name}' targets don't resolve to exactly one of all/agent_ids/filters: {exc}") from None

    severity = policy.severity or "MEDIUM"
    if severity not in _VALID_SEVERITIES:
        raise PolicyMigrationError(f"Policy '{policy.name}' has severity '{severity}', not one of {_VALID_SEVERITIES}")

    config = _step_config(step_type, action.get("params") or {})
    requires_approval = bool((policy.execution or {}).get("requires_approval"))

    if requires_approval:
        steps = [
            WorkflowStep(id="approval", type="approval", name="Approve", config={}),
            WorkflowStep(id="run", type=step_type, name=policy.name, config=config),
        ]
        edges = [WorkflowEdge(from_="approval", to="run", on="success")]
    else:
        steps = [WorkflowStep(id="run", type=step_type, name=policy.name, config=config)]
        edges = []

    return WorkflowDocument(
        metadata=WorkflowMetadata(
            name=_slugify(policy.name, policy.id),
            description=policy.description or f"Migrated from policy '{policy.name}' ({policy.id}).",
            severity=severity,
            tags=[*list(policy.tags or []), "migrated-from-policy"],
        ),
        spec=WorkflowSpec(targets=targets, steps=steps, edges=edges),
    )


async def import_policy_as_workflow(
    db: AsyncSession, storage: ObjectStorage, policy: Policy, *, created_by: UUID | None
) -> Workflow:
    """Idempotent: a policy already imported (migrated_from_policy_id set on
    some workflow) returns that workflow unchanged rather than creating a
    second one. The created workflow is published immediately — an
    unpublished import can't run or be scheduled, which would silently break
    the "both work" guarantee stage B promises."""
    existing = (await db.execute(
        select(Workflow).where(Workflow.migrated_from_policy_id == policy.id)
    )).scalar_one_or_none()
    if existing is not None:
        return existing

    doc = _build_document(policy)
    yaml_source = serialize_document(doc)

    svc = WorkflowService(db, storage)
    workflow = await svc.create_workflow(name=policy.name, yaml_source=yaml_source, created_by=created_by)

    workflow.migrated_from_policy_id = policy.id
    workflow.trigger_type = policy.trigger_type
    workflow.cron_expr = policy.cron_expr
    workflow.priority = policy.priority
    workflow.is_enabled = policy.is_enabled
    await db.commit()

    version = (await db.execute(
        select(WorkflowVersion).where(WorkflowVersion.workflow_id == workflow.id, WorkflowVersion.version == 1)
    )).scalar_one()
    await svc.publish_version(workflow.id, version.id, actor=created_by)
    await db.refresh(workflow)
    return workflow
