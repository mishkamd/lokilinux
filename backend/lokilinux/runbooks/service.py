"""
LokiLinux — Runbook service: incident_type matcher + Workflow Engine bridge.

Execution reuses services/workflow_engine.py::start_run end to end — no
duplicated execution logic.

Simplification vs. the plan's literal text ("targeting hosts from
incident_signals"): start_run has no parameter for a caller-supplied target
list — a published WorkflowVersion's targets are fixed at publish time
(baked into its compiled graph), same as a user clicking "Run" in the UI.
An AUTO-triggered runbook runs the workflow against ITS OWN configured
targets, not a dynamic per-incident host list. Scoping a run to the
specific incident's hosts is a real, larger change to start_run's
signature (also used by the manual-run router and the cron scheduler) —
a follow-up, not something a safe-by-default (AUTO off) MVP needs to block on.
"""

from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.runbooks.models import Runbook
from lokilinux.services.workflow_engine import start_run

logger = structlog.get_logger()

_SEVERITY_RANK = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}
_TENANT_ID = "default"


async def find_matching_runbooks(
    db: AsyncSession, incident_type: str, incident_severity: str, *, tenant_id: str = _TENANT_ID
) -> list[Runbook]:
    rows = (
        await db.execute(
            select(Runbook).where(
                Runbook.tenant_id == tenant_id,
                Runbook.incident_type == incident_type,
                Runbook.enabled.is_(True),
            )
        )
    ).scalars().all()
    incident_rank = _SEVERITY_RANK.get(incident_severity, 0)
    return [r for r in rows if _SEVERITY_RANK.get(r.min_severity, 0) <= incident_rank]


async def execute_runbook(
    db: AsyncSession, cache: Any, storage: Any, runbook: Runbook, *, nats: Any = None
) -> Any:
    if runbook.workflow_id is None:
        raise ValueError(f"runbook {runbook.id} has no workflow_id configured")
    return await start_run(
        db, cache, storage, runbook.workflow_id, trigger_type="API", triggered_by=None, nats=nats
    )


async def maybe_auto_run(
    db: AsyncSession, cache: Any, storage: Any, incident_type: str, incident_severity: str, *,
    autorun_enabled: bool, tenant_id: str = _TENANT_ID, nats: Any = None,
) -> list[Any]:
    """Called from IncidentWorker on INCIDENT_CREATED. autorun_enabled is
    the global kill switch (settings_schema "observability.
    incident_autorun_runbooks") — MANUAL runbooks are never touched here,
    they only run through routers/runbooks.py's explicit execute endpoint
    (Task F1)."""
    matches = await find_matching_runbooks(db, incident_type, incident_severity, tenant_id=tenant_id)
    runs = []
    for runbook in matches:
        if runbook.trigger_mode != "AUTO":
            continue
        if not autorun_enabled:
            logger.info("runbook.auto_run_skipped_kill_switch", runbook_id=str(runbook.id))
            continue
        try:
            runs.append(await execute_runbook(db, cache, storage, runbook, nats=nats))
        except Exception:
            logger.error("runbook.auto_run_failed", runbook_id=str(runbook.id), exc_info=True)
    return runs
