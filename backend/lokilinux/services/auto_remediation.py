"""
LokiLinux — AUTOMATIC remediation eligibility (Enterprise Compliance plan
U7/KTD8, Autopilot A2 §docs/modules/10-compliance-autopilot.md). Pure
precondition checks, no side effects and no plan creation here — this is
the "can this (agent, rule) be auto-remediated right now" question in
isolation, so it's testable without a scheduler tick or a real Job.

Full precondition list (plan U7 Task 2), evaluated in order:
  global kill-switch (compliance.auto_remediation_enabled)  -- checked by caller
  domain in policy.remediation.allowed and not in .forbidden
  an active RemediationTemplate exists for the rule with a non-empty rollback_body
  an open maintenance window covers the agent
  no other plan is already EXECUTING/VERIFYING for this same (agent, rule)
  daily cap not exceeded                                    -- checked by caller (batch-level)
Dry-run PASS is NOT a precondition checked here — it happens after plan
creation, gating the move from staged to actually dispatched (Autopilot A2
flow step 2).
"""

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.models.agent import Agent
from lokilinux.models.compliance_rule import (
    ComplianceRule,
    PolicySet,
    PolicySetRule,
    RemediationTemplate,
)
from lokilinux.models.remediation import MaintenanceWindow, RemediationAction, RemediationPlan
from lokilinux.services.remediation_service import _is_window_open, agent_matches_window_scope


def domain_allowed(remediation: dict | None, domain: str) -> bool:
    """`remediation` is a policy_sets.remediation JSONB value (or None).
    Empty/absent `allowed` means every domain is eligible except what's
    listed in `forbidden` — an admin opting into AUTOMATIC without an
    allowlist gets "everything this policy covers", not "nothing"."""
    remediation = remediation or {}
    if domain in (remediation.get("forbidden") or []):
        return False
    allowed = remediation.get("allowed") or []
    return not allowed or domain in allowed


async def find_automatic_policy(db: AsyncSession, rule_id: UUID) -> PolicySet | None:
    """The AUTOMATIC-mode policy this rule belongs to, if any. A rule can
    sit in several policy sets with different modes — AUTOMATIC wins if ANY
    covering enabled policy asks for it (opt-in explicit per policy, not a
    fleet-wide vote)."""
    policies = (
        (
            await db.execute(
                select(PolicySet)
                .join(PolicySetRule, PolicySetRule.policy_set_id == PolicySet.id)
                .where(PolicySetRule.rule_id == rule_id, PolicySet.is_enabled.is_(True))
            )
        )
        .scalars()
        .all()
    )
    for p in policies:
        if (p.remediation or {}).get("mode") == "AUTOMATIC":
            return p
    return None


async def eligible_for_automatic(
    db: AsyncSession, agent_id: UUID, rule: ComplianceRule, policy: PolicySet
) -> tuple[bool, str]:
    """Returns (eligible, reason) — reason is empty on success, otherwise
    names the first precondition that failed."""
    if not domain_allowed(policy.remediation, rule.domain):
        return False, "domain not in policy allowlist"

    template = (
        await db.execute(
            select(RemediationTemplate)
            .where(RemediationTemplate.rule_key == rule.rule_key)
            .order_by(RemediationTemplate.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if template is None:
        return False, "no remediation template for this rule"
    if not template.rollback_body:
        return False, "template has no rollback_body"

    agent = await db.get(Agent, agent_id)
    if agent is None:
        return False, "agent not found"

    windows = (
        (await db.execute(select(MaintenanceWindow).where(MaintenanceWindow.is_enabled.is_(True))))
        .scalars()
        .all()
    )
    now = datetime.now(timezone.utc)
    covered = any(
        _is_window_open(w, now)
        and agent_matches_window_scope(
            agent_os_distro=agent.os_distro,
            agent_os_version=agent.os_version,
            agent_tags=agent.tags or {},
            agent_custom_facts=agent.custom_facts or {},
            # ponytail: CATEGORY/PROJECT-scoped windows need name resolution
            # (see remediation_scheduler.py's Category/Project lookup) this
            # module doesn't do — fails closed (no match) for those two
            # scope types rather than mis-resolving, so AUTOMATIC simply
            # never fires through a category/project window today. Wire
            # the same lookup here if that combination is actually needed.
            category_name=None,
            project_name=None,
            window=w,
        )
        for w in windows
    )
    if not covered:
        return False, "no open maintenance window covers this agent"

    already_running = (
        await db.execute(
            select(RemediationAction.remediation_plan_id)
            .join(RemediationPlan, RemediationPlan.id == RemediationAction.remediation_plan_id)
            .where(
                RemediationAction.agent_id == agent_id,
                RemediationAction.rule_id == rule.id,
                RemediationPlan.status.in_(("EXECUTING", "VERIFYING")),
            )
            .limit(1)
        )
    ).first()
    if already_running is not None:
        return False, "a plan is already executing/verifying for this agent+rule"

    return True, ""


async def is_monitor_only(db: AsyncSession, rule_id: UUID) -> bool:
    """True when every enabled policy covering this rule is MONITOR mode —
    i.e. nothing permits remediating it at all (plan U7 Task 3). A rule
    with no covering policy, or covered by at least one ASSISTED/AUTOMATIC
    policy alongside a MONITOR one, is NOT blocked — MONITOR only wins when
    it's the only voice, mirroring find_automatic_policy's "any policy
    opts in" logic inverted (any policy that allows it wins over MONITOR)."""
    policies = (
        (
            await db.execute(
                select(PolicySet)
                .join(PolicySetRule, PolicySetRule.policy_set_id == PolicySet.id)
                .where(PolicySetRule.rule_id == rule_id, PolicySet.is_enabled.is_(True))
            )
        )
        .scalars()
        .all()
    )
    if not policies:
        return False
    return all((p.remediation or {}).get("mode") == "MONITOR" for p in policies)


async def plans_created_today(db: AsyncSession, since: datetime) -> int:
    """Daily cap counter — AUTOMATIC-trigger_type plans created since
    `since` (caller passes today's start in UTC), shared across the whole
    fleet per plan U7 Task 2 (not per-policy)."""
    from sqlalchemy import func

    return (
        await db.execute(
            select(func.count())
            .select_from(RemediationPlan)
            .where(RemediationPlan.trigger_type == "AUTOMATIC", RemediationPlan.created_at >= since)
        )
    ).scalar_one()
