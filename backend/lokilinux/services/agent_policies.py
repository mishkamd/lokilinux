"""
LokiLinux — Agent policy management service.

Owns the lifecycle: draft versions → publish (sign + immutable) → assign →
deploy (fan-out + desired version stamp) → rollback (new deployment to an
old version). Every mutation lands in agent_policy_audit.

Pydantic schemas ride in this module too — one import site for routers
(the plan's API surface is a single admin-facing domain; splitting schemas
into their own module adds indirection without a second consumer).
"""

import hashlib
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.models.agent import Agent
from lokilinux.models.agent_policy import (
    AgentGroup,
    AgentPolicy,
    AgentPolicyAssignment,
    AgentPolicyAudit,
    AgentPolicyDeployment,
    AgentPolicyVersion,
    EnrollmentToken,
    ScopeType,
)
from lokilinux.services import agent_policy_compiler as compiler

logger = logging.getLogger(__name__)


# ── Schemas ───────────────────────────────────────────────────────────────────


class PolicyCreate(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    description: str = ""
    yaml_text: str = ""  # empty = start from minimal skeleton


class PolicyUpdate(BaseModel):
    description: str | None = None
    yaml_text: str | None = None  # draft-only edit; published ⇒ new version instead


class PolicyOut(BaseModel):
    id: str
    name: str
    description: str
    status: str
    current_version: int | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def of(cls, p: AgentPolicy) -> "PolicyOut":
        return cls(
            id=str(p.id), name=p.name, description=p.description, status=p.status,
            current_version=p.current_version,
            created_at=p.created_at, updated_at=p.updated_at,
        )


class VersionOut(BaseModel):
    id: str
    version: int
    payload_hash: str
    signature: str
    signing_key_id: str
    status: str
    created_at: datetime

    @classmethod
    def of(cls, v: AgentPolicyVersion) -> "VersionOut":
        return cls(
            id=str(v.id), version=v.version, payload_hash=v.payload_hash[:16],
            signature=v.signature[:16], signing_key_id=v.signing_key_id,
            status=v.status, created_at=v.created_at,
        )


class VersionCreate(BaseModel):
    yaml_text: str


class PublishRequest(BaseModel):
    version_id: str


class AssignmentCreate(BaseModel):
    scope_type: str = "AGENT"
    scope_ref: str | None = None
    version_id: str | None = None
    rollout_strategy: str = "immediate"
    enabled: bool = True


class DeployRequest(BaseModel):
    scope_type: str = "AGENT"
    scope_ref: str | None = None
    rollout_strategy: str = "immediate"


class RollbackRequest(BaseModel):
    to_version: int


class GroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class EnrollmentTokenCreate(BaseModel):
    label: str = ""
    ttl_hours: int = Field(default=24, ge=1, le=720)
    single_use: bool = True
    agent_group: str | None = None


def _tenant() -> str:
    return "default"


async def _audit(db: AsyncSession, action: str, resource_type: str, resource_id: Optional[uuid.UUID],
                 old_version: Optional[int] = None, new_version: Optional[int] = None,
                 result: str = "ok", error: str | None = None) -> None:
    db.add(AgentPolicyAudit(
        action=action, resource_type=resource_type, resource_id=resource_id,
        old_version=old_version, new_version=new_version, result=result, error=error,
    ))


def canonical_bytes(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


# ── Policies ──────────────────────────────────────────────────────────────────


class AgentPolicyService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_policies(self, limit: int = 50, cursor: str | None = None):
        q = (
            select(AgentPolicy)
            .where(AgentPolicy.tenant_id == _tenant())
            .order_by(AgentPolicy.created_at.desc(), AgentPolicy.id.desc())
            .limit(limit + 1)
        )
        rows = (await self.db.execute(q)).scalars().all()
        has_more = len(rows) > limit
        items = rows[:limit]
        next_cursor = items[-1].created_at.isoformat() if has_more and items else None
        total = (
            await self.db.execute(
                select(func.count()).select_from(AgentPolicy).where(AgentPolicy.tenant_id == _tenant())
            )
        ).scalar()
        return items, next_cursor, total

    async def get_policy(self, policy_id) -> AgentPolicy:
        row = await self.db.get(AgentPolicy, policy_id if isinstance(policy_id, uuid.UUID) else uuid.UUID(policy_id))
        if not row:
            raise HTTPException(404, "Policy not found")
        return row

    async def create_policy(self, body: PolicyCreate, actor=None) -> AgentPolicy:
        exists = (
            await self.db.execute(
                select(AgentPolicy).where(
                    AgentPolicy.tenant_id == _tenant(), AgentPolicy.name == body.name
                )
            )
        ).scalar_one_or_none()
        if exists:
            raise HTTPException(409, f"Policy '{body.name}' already exists")

        if body.yaml_text.strip():
            doc = compiler.validate(compiler.parse_yaml(body.yaml_text))
            if doc["metadata"]["name"] != body.name:
                doc["metadata"]["name"] = body.name
                compiler.validate(doc)
        else:
            doc = compiler.validate({
                "apiVersion": "lokilinux.io/v1",
                "kind": "AgentPolicy",
                "metadata": {"name": body.name},
            })

        policy = AgentPolicy(name=body.name, description=body.description, status="draft", created_by=actor)
        self.db.add(policy)
        await self.db.flush()

        v = AgentPolicyVersion(
            policy_id=policy.id, version=1, payload=doc,
            payload_hash=compiler.payload_hash(doc), status="draft", created_by=actor,
        )
        self.db.add(v)
        await _audit(self.db, "create", "agent_policy", policy.id, new_version=1)
        return policy

    async def update_policy(self, policy_id, body: PolicyUpdate, actor=None) -> AgentPolicy:
        policy = await self.get_policy(policy_id)
        if body.description is not None:
            policy.description = body.description
        if body.yaml_text is not None and body.yaml_text.strip():
            if policy.status != "draft":
                raise HTTPException(409, "Published policies are immutable — POST /versions to create a new one")
            # replace the draft version payload (only when it's still unpublished)
            doc = compiler.validate(compiler.parse_yaml(body.yaml_text))
            if doc["metadata"]["name"] != policy.name:
                doc["metadata"]["name"] = policy.name
                compiler.validate(doc)
            draft = (
                await self.db.execute(
                    select(AgentPolicyVersion).where(
                        AgentPolicyVersion.policy_id == policy.id,
                        AgentPolicyVersion.version == 1,
                        AgentPolicyVersion.status == "draft",
                    )
                )
            ).scalar_one_or_none()
            if not draft:
                raise HTTPException(409, "No editable draft version — clone or publish")
            draft.payload = doc
            draft.payload_hash = compiler.payload_hash(doc)
        await _audit(self.db, "update", "agent_policy", policy.id)
        return policy

    async def delete_policy(self, policy_id, actor=None) -> None:
        policy = await self.get_policy(policy_id)
        active_assignments = (
            await self.db.execute(
                select(func.count()).select_from(AgentPolicyAssignment).where(
                    AgentPolicyAssignment.policy_id == policy.id,
                    AgentPolicyAssignment.enabled.is_(True),
                )
            )
        ).scalar()
        if active_assignments:
            raise HTTPException(409, "Policy has active assignments")
        if policy.status != "archived":
            policy.status = "archived"
            await _audit(self.db, "update", "agent_policy", policy.id)
            return  # archive-first; hard delete only from archived state
        await self.db.delete(policy)

    async def list_versions(self, policy_id):
        await self.get_policy(policy_id)
        rows = (
            await self.db.execute(
                select(AgentPolicyVersion)
                .where(AgentPolicyVersion.policy_id == policy_id)
                .order_by(AgentPolicyVersion.version.desc())
            )
        ).scalars().all()
        return rows

    async def get_version(self, policy_id, version: Optional[int] = None, version_id: Optional[str] = None) -> AgentPolicyVersion:
        if version_id:
            row = await self.db.get(AgentPolicyVersion, uuid.UUID(version_id))
        elif version is not None:
            row = (
                await self.db.execute(
                    select(AgentPolicyVersion).where(
                        AgentPolicyVersion.policy_id == policy_id,
                        AgentPolicyVersion.version == version,
                    )
                )
            ).scalar_one_or_none()
        else:
            row = None
        if not row:
            raise HTTPException(404, "Version not found")
        return row

    async def create_version(self, policy_id, body: VersionCreate, actor=None) -> AgentPolicyVersion:
        policy = await self.get_policy(policy_id)
        latest = (
            await self.db.execute(
                select(func.max(AgentPolicyVersion.version)).where(AgentPolicyVersion.policy_id == policy.id)
            )
        ).scalar() or 0
        doc = compiler.validate(compiler.parse_yaml(body.yaml_text))
        if doc["metadata"]["name"] != policy.name:
            doc["metadata"]["name"] = policy.name
            compiler.validate(doc)
        v = AgentPolicyVersion(
            policy_id=policy.id, version=int(latest) + 1, payload=doc,
            payload_hash=compiler.payload_hash(doc), status="draft", created_by=actor,
        )
        self.db.add(v)
        await _audit(self.db, "update", "agent_policy", policy.id, new_version=v.version)
        return v

    async def publish_version(self, policy_id, body: PublishRequest, actor=None) -> AgentPolicyVersion:
        """Sign + freeze. The stored hash stays authoritative even across
        re-signings caused by key rotation — the agent verifies signature over
        canonical bytes AND compares the fetched payload's sha256 with
        payload_hash, so both bindings hold."""
        policy = await self.get_policy(policy_id)
        v = await self.get_version(policy.id, version_id=body.version_id)
        if v.status == "published":
            raise HTTPException(409, "Already published (immutable)")
        v.signature = compiler.sign_payload(v.payload)
        v.status = "published"
        previous = policy.current_version
        policy.status = "active"
        policy.current_version = v.version
        policy.updated_at = datetime.now(timezone.utc)
        await _audit(self.db, "publish", "agent_policy", policy.id,
                     old_version=previous, new_version=v.version)
        return v

    async def from_template(self, template_key: str, name: str, actor=None) -> AgentPolicy:
        template = (
            await self.db.execute(
                select(AgentPolicy).where(
                    AgentPolicy.tenant_id == _tenant(), AgentPolicy.name == template_key
                )
            )
        ).scalar_one_or_none()
        if not template:
            raise HTTPException(404, f"Template {template_key!r} not found")
        body = PolicyCreate(name=name, description=f"Cloned from {template_key}.", yaml_text="")
        policy = await self.create_policy(body, actor)
        src = (
            await self.db.execute(
                select(AgentPolicyVersion).where(
                    AgentPolicyVersion.policy_id == template.id,
                    AgentPolicyVersion.version == (template.current_version or 1),
                )
            )
        ).scalar_one_or_none()
        if src:
            draft = (
                await self.db.execute(
                    select(AgentPolicyVersion).where(AgentPolicyVersion.policy_id == policy.id)
                )
            ).scalar_one()
            payload = dict(src.payload)
            payload.setdefault("metadata", {})["name"] = name
            payload = compiler.validate(payload)
            draft.payload = payload
            draft.payload_hash = compiler.payload_hash(payload)
        return policy

    # ── Assignments & deployments ─────────────────────────────────────────────

    async def create_assignment(self, policy_id, body: AssignmentCreate, actor=None) -> AgentPolicyAssignment:
        policy = await self.get_policy(policy_id)
        try:
            scope_type = ScopeType(body.scope_type)
        except ValueError as exc:
            raise HTTPException(422, f"Invalid scope_type {body.scope_type!r}") from exc

        version_id = None
        if body.version_id:
            v = await self.get_version(policy.id, version_id=body.version_id)
            if v.status != "published":
                raise HTTPException(409, "Only published versions are deployable")
            version_id = v.id

        assignment = AgentPolicyAssignment(
            policy_id=policy.id, version_id=version_id,
            scope_type=scope_type.value, scope_ref=uuid.UUID(body.scope_ref) if body.scope_ref else None,
            rollout_strategy=body.rollout_strategy, enabled=body.enabled, created_by=actor,
        )
        self.db.add(assignment)
        await _audit(self.db, "assign", "agent_policy_assignment", assignment.id)
        return assignment

    async def deploy(self, policy_id, body: DeployRequest, actor=None, nats_client=None) -> list[dict]:
        """Stamp desired policy on matching agents and open deployments.

        Fan-out resolution by scope:
          AGENT  → that agent
          GROUP  → agents whose group matches (agents table has no group column;
                   groups resolve through enrollment tokens' agent_group at
                   enroll time, stored on the agent row via last_enrollment_group?
                   — MVP simplification: GROUP scope matches nothing until an
                   explicit mapping ships; keeping the branch honest here.)
          TENANT → every ACTIVE agent in the tenant.
        """
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        policy = await self.get_policy(policy_id)
        assignment = AgentPolicyAssignment(
            policy_id=policy.id, version_id=None, scope_type=body.scope_type,
            scope_ref=uuid.UUID(body.scope_ref) if body.scope_ref else None,
            rollout_strategy=body.rollout_strategy, created_by=actor,
        )
        version_id = (
            await self.db.execute(
                select(AgentPolicyVersion.id).where(
                    AgentPolicyVersion.policy_id == policy.id,
                    AgentPolicyVersion.version == policy.current_version,
                    AgentPolicyVersion.status == "published",
                )
            )
        ).scalar_one_or_none()
        if not version_id:
            raise HTTPException(409, "Policy has no published current version")

        q = select(Agent).where(Agent.status == "ACTIVE")
        if body.scope_type == "GROUP":
            if not body.scope_ref:
                raise HTTPException(422, "scope_ref required for GROUP scope")
            q = q.where(Agent.enrollment_group_id == uuid.UUID(body.scope_ref))
        elif body.scope_type == "AGENT":
            q = q.where(Agent.id == uuid.UUID(body.scope_ref))
        agents = (await self.db.execute(q)).scalars().all()
        if not agents:
            raise HTTPException(409, "No matching agents for deployment")

        self.db.add(assignment)
        await self.db.flush()

        out = []
        for agent in agents:
            deployment = AgentPolicyDeployment(
                assignment_id=assignment.id, agent_id=agent.id, version_id=version_id,
            )
            self.db.add(deployment)
            await self.db.flush()
            # desired stamp is an UPDATE so redeploys overwrite cleanly
            await self.db.execute(
                sa_update(Agent)
                .where(Agent.agent_id == agent.agent_id)
                .values(desired_policy_version_id=version_id, policy_status="pending")
            )
            out.append({"deployment_id": str(deployment.id), "agent_id": str(agent.id),
                        "agent_identity": agent.agent_id})
            await _audit(self.db, "deploy", "agent_policy_deployment", deployment.id,
                         new_version=policy.current_version)

        await self._notify_deployments(out, policy.id, policy.current_version)
        return out

    async def _notify_deployments(self, deployments: list[dict], policy_id, version: int,
                                  nats_client=None) -> None:
        """Best-effort NATS notify — heartbeat reconciliation covers agents who
        miss it. Never raises. nats_client comes from the router's request.app.state."""
        if nats_client is None:
            return
        try:
            for d in deployments:
                subject = f"lokilinux.agent.policy.updated.{d['agent_identity']}"
                await nats_client.publish(
                    subject,
                    json.dumps({
                        "policy_id": str(policy_id),
                        "version": version,
                        "deployment_id": d["deployment_id"],
                    }).encode(),
                )
            await nats_client.flush()
        except Exception:  # noqa: BLE001
            logger.warning("policy notification failed — falling back to heartbeat reconcile")

    async def rollback(self, agent_row_id, body: RollbackRequest, actor=None, nats_client=None) -> dict:
        """Rollback = NEW deployment pointing at an older published version."""
        agent = (
            await self.db.execute(select(Agent).where(Agent.id == agent_row_id))
        ).scalar_one_or_none()
        if not agent:
            raise HTTPException(404, "Agent not found")
        current_v = (
            await self.db.execute(
                select(AgentPolicyVersion).where(AgentPolicyVersion.id == agent.desired_policy_version_id)
            )
        ).scalar_one_or_none()
        target = (
            await self.db.execute(
                select(AgentPolicyVersion).where(
                    AgentPolicyVersion.policy_id == current_v.policy_id if current_v else AgentPolicyVersion.id == agent.desired_policy_version_id,
                    AgentPolicyVersion.version == body.to_version,
                    AgentPolicyVersion.status == "published",
                )
            ).scalar_one_or_none()
            if current_v
            else None
        )
        if not target:
            raise HTTPException(404, f"Published version {body.to_version} not found for this agent's policy")

        deployment = AgentPolicyDeployment(
            agent_id=agent.id, version_id=target.id,
        )
        self.db.add(deployment)
        await self.db.flush()
        agent.desired_policy_version_id = target.id
        agent.policy_status = "pending"
        await _audit(self.db, "rollback", "agent_policy_deployment", deployment.id,
                     old_version=current_v.version if current_v else None,
                     new_version=target.version)
        await self._notify_deployments(
            [{"deployment_id": str(deployment.id), "agent_identity": agent.agent_id}],
            target.policy_id, target.version, nats_client,
        )
        return {"deployment_id": str(deployment.id), "to_version": target.version}

    async def agent_policy_state(self, agent_row_id) -> dict:
        """Desired vs actual for one agent — feeds the UI drift panel."""
        agent = (
            await self.db.execute(select(Agent).where(Agent.id == agent_row_id))
        ).scalar_one_or_none()
        if not agent:
            raise HTTPException(404, "Agent not found")
        desired = actual = None
        if agent.desired_policy_version_id:
            row = await self.db.get(AgentPolicyVersion, agent.desired_policy_version_id)
            pol = await self.db.get(AgentPolicy, row.policy_id)
            desired = {"policy": pol.name, "version": row.version, "hash": row.payload_hash}
        if agent.current_policy_version_id:
            row = await self.db.get(AgentPolicyVersion, agent.current_policy_version_id)
            pol = await self.db.get(AgentPolicy, row.policy_id)
            actual = {"policy": pol.name, "version": row.version, "hash": row.payload_hash}
        in_sync = bool(desired and actual and desired["hash"] == actual["hash"])
        return {
            "desired": desired,
            "actual": actual,
            "in_sync": in_sync,
            "status": agent.policy_status,
            "last_error": agent.policy_last_error,
        }

    # ── Groups ────────────────────────────────────────────────────────────────

    async def create_group(self, body: GroupCreate, actor=None) -> AgentGroup:
        exists = (
            await self.db.execute(
                select(AgentGroup).where(
                    AgentGroup.tenant_id == _tenant(), AgentGroup.name == body.name
                )
            )
        ).scalar_one_or_none()
        if exists:
            raise HTTPException(409, f"Group '{body.name}' already exists")
        group = AgentGroup(name=body.name)
        self.db.add(group)
        await self.db.flush()
        await _audit(self.db, "create", "agent_group", group.id)
        return group

    async def list_groups(self):
        return (
            await self.db.execute(
                select(AgentGroup).where(AgentGroup.tenant_id == _tenant()).order_by(AgentGroup.name)
            )
        ).scalars().all()

    # ── Enrollment tokens (DB-backed) ─────────────────────────────────────────

    @staticmethod
    def hash_token(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    async def issue_enrollment_token(self, body: EnrollmentTokenCreate, actor=None) -> dict:
        """Generates a cryptographically random token; stores only its hash.
        The plaintext is returned exactly once — it lives nowhere else."""
        import secrets

        group_id = uuid.UUID(body.agent_group) if body.agent_group else None
        plaintext = secrets.token_urlsafe(24)
        row = EnrollmentToken(
            token_hash=self.hash_token(plaintext),
            label=body.label,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=body.ttl_hours),
            single_use=body.single_use,
            agent_group=group_id,
            created_by=actor,
        )
        self.db.add(row)
        await self.db.flush()
        await _audit(self.db, "create", "enrollment_token", row.id)
        return {
            "id": str(row.id),
            "token": plaintext,  # one-time disclosure
            "expires_at": row.expires_at.isoformat(),
            "single_use": row.single_use,
        }

    async def list_enrollment_tokens(self) -> list[dict]:
        rows = (
            await self.db.execute(
                select(EnrollmentToken).where(EnrollmentToken.tenant_id == _tenant())
                .order_by(EnrollmentToken.created_at.desc())
            )
        ).scalars().all()
        now = datetime.now(timezone.utc)
        return [
            {
                "id": str(r.id), "label": r.label,
                "expires_at": r.expires_at.isoformat(),
                "used_at": r.used_at.isoformat() if r.used_at else None,
                "revoked_at": r.revoked_at.isoformat() if r.revoked_at else None,
                "single_use": r.single_use,
                "status": (
                    "revoked" if r.revoked_at else
                    "used" if r.used_at and r.single_use else
                    "expired" if r.expires_at < now else
                    "active"
                ),
            }
            for r in rows
        ]

    async def revoke_enrollment_token(self, token_row_id, actor=None) -> None:
        row = await self.db.get(EnrollmentToken, token_row_id)
        if not row:
            raise HTTPException(404, "Token not found")
        if row.revoked_at is None:
            row.revoked_at = datetime.now(timezone.utc)
            await _audit(self.db, "revoke_token", "enrollment_token", row.id)

    async def validate_enrollment_token(self, plaintext: str) -> EnrollmentToken:
        """Single validation entry point used by POST /agents/register. Checks
        hash → expiry → revocation → single-use. Marks used atomically enough
        for the fleet's enrollment volume (one admin action per host)."""
        row = (
            await self.db.execute(
                select(EnrollmentToken).where(EnrollmentToken.token_hash == self.hash_token(plaintext))
            )
        ).scalar_one_or_none()
        if not row:
            raise HTTPException(403, "Invalid enrollment token")
        if row.revoked_at:
            raise HTTPException(403, "Token revoked")
        if row.expires_at < datetime.now(timezone.utc):
            raise HTTPException(403, "Token expired")
        if row.single_use and row.used_at:
            raise HTTPException(403, "Token already used (single-use)")
        if row.single_use:
            row.used_at = datetime.now(timezone.utc)
        return row
