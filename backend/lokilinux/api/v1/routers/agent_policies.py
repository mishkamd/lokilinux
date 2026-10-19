"""
LokiLinux — Agent policy management endpoints.

Plan: docs/superpowers/plans/2026-08-23-agent-policy-modernization-plan.md §6.
RBAC: ADMIN/OPERATOR for management, ADMIN for destructive ops; read access
ADMIN/OPERATOR/AUDITOR (VIEWER intentionally excluded — policies shape what
agents DO, which is operational knowledge).
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.auth.dependencies import get_current_user, require_role
from lokilinux.dependencies import get_db
from lokilinux.services.agent_policies import (
    AgentPolicyService,
    AssignmentCreate,
    DeployRequest,
    EnrollmentTokenCreate,
    GroupCreate,
    PolicyCreate,
    PolicyUpdate,
    PublishRequest,
    RollbackRequest,
    VersionCreate,
)

router = APIRouter()


async def _svc(db: AsyncSession = Depends(get_db)) -> AgentPolicyService:
    return AgentPolicyService(db)


def _nats(request: Request):
    return getattr(request.app.state, "nats", None)


# ── Policies ──────────────────────────────────────────────────────────────────


@router.get("", dependencies=[Depends(require_role("OPERATOR", "AUDITOR"))])
async def list_policies(limit: int = 50, svc: AgentPolicyService = Depends(_svc)):
    items, next_cursor, total = await svc.list_policies(limit=limit)
    return {
        "items": [{"id": p.id, "name": p.name, "description": p.description,
                   "status": p.status, "current_version": p.current_version} for p in items],
        "next_cursor": next_cursor,
        "total": total,
    }


@router.post("", status_code=201)
async def create_policy(body: PolicyCreate, request: Request, svc: AgentPolicyService = Depends(_svc),
                        user: dict = Depends(require_role("OPERATOR"))):
    from lokilinux.auth.dependencies import safe_user_uuid

    policy = await svc.create_policy(body, actor=safe_user_uuid(user))
    return {"id": str(policy.id), "name": policy.name, "status": policy.status}


@router.get("/{policy_id}")
async def get_policy(policy_id: uuid.UUID, svc: AgentPolicyService = Depends(_svc),
                     user: dict = Depends(get_current_user)):
    """Detail includes the full payload of the current version — the editor's
    data source. VIEWER read is fine here; edits are gated per-endpoint."""
    policy = await svc.get_policy(policy_id)
    versions = await svc.list_versions(policy.id)
    current = next((v for v in versions if v.version == policy.current_version), None)
    return {
        "id": str(policy.id), "name": policy.name, "description": policy.description,
        "status": policy.status, "current_version": policy.current_version,
        "payload": current.payload if current else None,
        "versions": [
            {"id": str(v.id), "version": v.version, "status": v.status,
             "payload_hash": v.payload_hash[:16], "signing_key_id": v.signing_key_id}
            for v in versions
        ],
    }


@router.put("/{policy_id}")
async def update_policy(policy_id: uuid.UUID, body: PolicyUpdate,
                        svc: AgentPolicyService = Depends(_svc),
                        user: dict = Depends(require_role("OPERATOR"))):
    from lokilinux.auth.dependencies import safe_user_uuid

    policy = await svc.update_policy(policy_id, body, actor=safe_user_uuid(user))
    return {"id": str(policy.id), "status": policy.status}


@router.delete("/{policy_id}")
async def delete_policy(policy_id: uuid.UUID, svc: AgentPolicyService = Depends(_svc),
                        user: dict = Depends(require_role("ADMIN"))):
    from lokilinux.auth.dependencies import safe_user_uuid

    await svc.delete_policy(policy_id, actor=safe_user_uuid(user))
    return {"deleted": True}


@router.post("/{policy_id}/clone")
async def clone_policy(policy_id: uuid.UUID, svc: AgentPolicyService = Depends(_svc),
                       user: dict = Depends(require_role("OPERATOR"))):
    raise HTTPException(501, "Use POST /agent-policies/from-template with the seeded templates")


@router.get("/{policy_id}/versions")
async def list_versions(policy_id: uuid.UUID, svc: AgentPolicyService = Depends(_svc),
                        user: dict = Depends(get_current_user)):
    rows = await svc.list_versions(policy_id)
    return {"items": [{"id": str(v.id), "version": v.version, "status": v.status,
                       "created_at": v.created_at.isoformat()} for v in rows]}


@router.get("/{policy_id}/payload")
async def get_version_payload(policy_id: uuid.UUID, version_id: str,
                              svc: AgentPolicyService = Depends(_svc),
                              user: dict = Depends(get_current_user)):
    """Full payload of one version — editor + verify views. Response carries
    the signature so the admin UI can offer local verification."""
    v = await svc.get_version(policy_id, version_id=version_id)
    return {"payload": v.payload, "signature": v.signature,
            "payload_hash": v.payload_hash, "signing_key_id": v.signing_key_id}


@router.post("/{policy_id}/versions")
async def create_version(policy_id: uuid.UUID, body: VersionCreate,
                         svc: AgentPolicyService = Depends(_svc),
                         user: dict = Depends(require_role("OPERATOR"))):
    from lokilinux.auth.dependencies import safe_user_uuid

    v = await svc.create_version(policy_id, body, actor=safe_user_uuid(user))
    return {"id": str(v.id), "version": v.version, "status": v.status}


@router.post("/{policy_id}/publish")
async def publish_version(policy_id: uuid.UUID, body: PublishRequest,
                          svc: AgentPolicyService = Depends(_svc),
                          user: dict = Depends(require_role("OPERATOR"))):
    from lokilinux.auth.dependencies import safe_user_uuid

    v = await svc.publish_version(policy_id, body, actor=safe_user_uuid(user))
    return {"version": v.version, "status": v.status,
            "signed_with": v.signing_key_id}


@router.get("/{policy_id}/audit")
async def policy_audit(policy_id: uuid.UUID, limit: int = 100,
                       db: AsyncSession = Depends(get_db),
                       user: dict = Depends(require_role("OPERATOR", "AUDITOR"))):
    from sqlalchemy import select
    from lokilinux.models.agent_policy import AgentPolicyAudit

    rows = (
        (await db.execute(
            select(AgentPolicyAudit)
            .where(AgentPolicyAudit.resource_id == policy_id)
            .order_by(AgentPolicyAudit.id.desc()).limit(limit)
        )).scalars().all()
    )
    return {"items": [{"action": r.action, "result": r.result, "old_version": r.old_version,
                       "new_version": r.new_version, "created_at": r.created_at.isoformat()}
                      for r in rows]}


# ── Templates ─────────────────────────────────────────────────────────────────


@router.get("/templates/list")
async def list_templates(svc: AgentPolicyService = Depends(_svc),
                         user: dict = Depends(get_current_user)):
    items, _, _ = await svc.list_policies(limit=200)
    seeded = [p for p in items if p.name.startswith(("linux-", "default-"))]
    return {"items": [{"name": t.name, "description": t.description,
                       "current_version": t.current_version} for t in seeded]}


@router.post("/from-template")
async def from_template(body: dict, svc: AgentPolicyService = Depends(_svc),
                        user: dict = Depends(require_role("OPERATOR"))):
    from lokilinux.auth.dependencies import safe_user_uuid

    name = str(body.get("name", "")).strip()
    template_key = str(body.get("template_key", "")).strip()
    if not name or not template_key:
        raise HTTPException(422, "name and template_key required")
    policy = await svc.from_template(template_key, name, actor=safe_user_uuid(user))
    return {"id": str(policy.id)}


# ── Assignment & deployment ───────────────────────────────────────────────────


@router.post("/{policy_id}/deploy")
async def deploy_policy(policy_id: uuid.UUID, body: DeployRequest, request: Request,
                        svc: AgentPolicyService = Depends(_svc),
                        user: dict = Depends(require_role("OPERATOR"))):
    from lokilinux.auth.dependencies import safe_user_uuid

    out = await svc.deploy(policy_id, body, actor=safe_user_uuid(user),
                           nats_client=_nats(request))
    return {"deployments": out, "count": len(out)}


@router.get("/{policy_id}/assignments")
async def list_assignments(policy_id: uuid.UUID,
                           db: AsyncSession = Depends(get_db),
                           user: dict = Depends(require_role("OPERATOR", "AUDITOR"))):
    from sqlalchemy import select
    from lokilinux.models.agent_policy import AgentPolicyAssignment

    rows = (
        (await db.execute(
            select(AgentPolicyAssignment).where(AgentPolicyAssignment.policy_id == policy_id)
            .order_by(AgentPolicyAssignment.created_at.desc())
        )).scalars().all()
    )
    return {"items": [{"id": str(a.id), "scope_type": a.scope_type,
                       "scope_ref": str(a.scope_ref) if a.scope_ref else None,
                       "rollout_strategy": a.rollout_strategy, "enabled": a.enabled}
                      for a in rows]}


@router.post("/{policy_id}/assignments")
async def create_assignment(policy_id: uuid.UUID, body: AssignmentCreate,
                            svc: AgentPolicyService = Depends(_svc),
                            user: dict = Depends(require_role("OPERATOR"))):
    from lokilinux.auth.dependencies import safe_user_uuid

    a = await svc.create_assignment(policy_id, body, actor=safe_user_uuid(user))
    return {"id": str(a.id), "scope_type": a.scope_type}


@router.delete("/assignments/{assignment_id}")
async def delete_assignment(assignment_id: uuid.UUID,
                            db: AsyncSession = Depends(get_db),
                            user: dict = Depends(require_role("OPERATOR"))):
    from lokilinux.models.agent_policy import AgentPolicyAssignment

    row = await db.get(AgentPolicyAssignment, assignment_id)
    if not row:
        raise HTTPException(404, "Assignment not found")
    row.enabled = False
    return {"disabled": True}


@router.get("/agents/{agent_row_id}/policy")
async def agent_policy_state(agent_row_id: uuid.UUID, svc: AgentPolicyService = Depends(_svc),
                             user: dict = Depends(require_role("OPERATOR", "AUDITOR"))):
    return await svc.agent_policy_state(agent_row_id)


@router.post("/agents/{agent_row_id}/policy/rollback")
async def rollback_agent_policy(agent_row_id: uuid.UUID, body: RollbackRequest, request: Request,
                                svc: AgentPolicyService = Depends(_svc),
                                user: dict = Depends(require_role("OPERATOR"))):
    from lokilinux.auth.dependencies import safe_user_uuid

    return await svc.rollback(agent_row_id, body, actor=safe_user_uuid(user),
                              nats_client=_nats(request))


@router.post("/agents/{agent_row_id}/policy/sync-now")
async def sync_now(agent_row_id: uuid.UUID, request: Request, db: AsyncSession = Depends(get_db),
                   user: dict = Depends(require_role("OPERATOR"))):
    """Force reconcile: re-publish the desired-version notification."""
    import json as _json
    from sqlalchemy import select as _select
    from lokilinux.models.agent import Agent

    agent = (await db.execute(_select(Agent).where(Agent.id == agent_row_id))).scalar_one_or_none()
    if not agent:
        raise HTTPException(404, "Agent not found")
    if not agent.desired_policy_version_id:
        raise HTTPException(409, "Agent has no desired policy to reconcile")
    nats = _nats(request)
    if nats is None:
        raise HTTPException(503, "NATS unavailable — heartbeat reconciliation will retry")
    from lokilinux.models.agent_policy import AgentPolicyVersion

    version_row = await db.get(AgentPolicyVersion, agent.desired_policy_version_id)
    subject = f"lokilinux.agent.policy.updated.{agent.agent_id}"
    await nats.publish(subject, _json.dumps({
        "policy_id": str(version_row.policy_id),
        "version": version_row.version,
    }).encode())
    await nats.flush()
    return {"notified": True, "desired_version": version_row.version}


# ── Groups ────────────────────────────────────────────────────────────────────


@router.get("/groups/list")
async def list_groups(svc: AgentPolicyService = Depends(_svc),
                      user: dict = Depends(require_role("OPERATOR", "AUDITOR"))):
    rows = await svc.list_groups()
    return {"items": [{"id": str(g.id), "name": g.name} for g in rows]}


@router.post("/groups")
async def create_group(body: GroupCreate, svc: AgentPolicyService = Depends(_svc),
                       user: dict = Depends(require_role("OPERATOR"))):
    from lokilinux.auth.dependencies import safe_user_uuid

    g = await svc.create_group(body, actor=safe_user_uuid(user))
    return {"id": str(g.id), "name": g.name}


# ── Enrollment tokens ─────────────────────────────────────────────────────────


@router.get("/enrollment-tokens")
async def list_enrollment_tokens(svc: AgentPolicyService = Depends(_svc),
                                 user: dict = Depends(require_role("ADMIN"))):
    return {"items": await svc.list_enrollment_tokens()}


@router.post("/enrollment-tokens")
async def issue_enrollment_token(body: EnrollmentTokenCreate, svc: AgentPolicyService = Depends(_svc),
                                 user: dict = Depends(require_role("ADMIN"))):
    from lokilinux.auth.dependencies import safe_user_uuid

    return await svc.issue_enrollment_token(body, actor=safe_user_uuid(user))


@router.delete("/enrollment-tokens/{token_id}")
async def revoke_enrollment_token(token_id: uuid.UUID, svc: AgentPolicyService = Depends(_svc),
                                  user: dict = Depends(require_role("ADMIN"))):
    from lokilinux.auth.dependencies import safe_user_uuid

    await svc.revoke_enrollment_token(token_id, actor=safe_user_uuid(user))
    return {"revoked": True}
