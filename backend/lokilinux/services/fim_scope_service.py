"""
LokiLinux — File-integrity scope service.

Owns the fim_scopes table (GLOBAL default + AGENT overrides) and the signed
document handed to the agent's FileIntegrityCollector over the heartbeat
(agent/internal/compliance/fimconfig.go). Signing reuses the platform's
existing policy-signing keypair (agent_policy_compiler.py) — agents already
pin "policy-signing-v1" at enrollment (install-agent.sh), so this rides the
same trust anchor instead of minting a second one.

Not to be confused with file_integrity_ignores (migration 017): that table
is a GLOBAL-only, unwritten, post-ingest filter applied server-side after
the agent has already scanned. fim_scopes controls what the agent scans in
the first place, and reaches every agent (not just ones with a policy
deployment) because it's delivered outside the desired-state policy channel.
"""

import os
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lokilinux.models.file_integrity import FIMScope
from lokilinux.services.agent_policy_compiler import canonical_bytes, sign_payload

SIGNING_KEY_ID = "policy-signing-v1"
MAX_PATHS_PER_LIST = 64


class FIMScopeValidationError(ValueError):
    """Raised for any watch/ignore path list the agent would be wrong to trust."""


def _validate_paths(paths: list, *, field: str, require_nonempty: bool = False) -> list[str]:
    if not isinstance(paths, list):
        raise FIMScopeValidationError(f"{field} must be a list of paths")
    if require_nonempty and len(paths) == 0:
        # An empty watch_paths list on a saved row isn't "watch nothing" —
        # SetPaths on the agent falls back to the compiled /etc default for
        # an empty list, so an override with none would look configured but
        # silently be a no-op. The Reset button is the correct way to fall
        # back to the global default; the textarea itself must not be empty.
        raise FIMScopeValidationError(f"{field}: at least one path is required (use Reset to fall back to the default instead)")
    if len(paths) > MAX_PATHS_PER_LIST:
        raise FIMScopeValidationError(f"{field}: at most {MAX_PATHS_PER_LIST} entries")
    cleaned: list[str] = []
    for p in paths:
        if not isinstance(p, str) or "\x00" in p:
            raise FIMScopeValidationError(f"{field}: invalid entry {p!r}")
        p = p.strip()
        if not p.startswith("/"):
            raise FIMScopeValidationError(f"{field}: {p!r} must be an absolute path")
        # normpath already collapses any ".." segment — on an absolute POSIX
        # path that can never escape above "/", so there's nothing left to
        # separately reject; it just resolves to a shorter absolute path.
        norm = os.path.normpath(p)
        if norm == "/":
            raise FIMScopeValidationError(f"{field}: '/' is not allowed — that would scan the whole filesystem")
        cleaned.append(norm)
    return cleaned


def version_of(scope: FIMScope) -> int:
    """Monotonic version for the signed envelope and the agent's replay
    guard — the row's own updated_at, which only moves forward."""
    return int(scope.updated_at.timestamp())


async def get_global_scope(db: AsyncSession) -> FIMScope | None:
    return (
        await db.execute(select(FIMScope).where(FIMScope.scope_type == "GLOBAL"))
    ).scalar_one_or_none()


async def get_agent_scope(db: AsyncSession, agent_id: uuid.UUID) -> FIMScope | None:
    return (
        await db.execute(
            select(FIMScope).where(FIMScope.scope_type == "AGENT", FIMScope.agent_id == agent_id)
        )
    ).scalar_one_or_none()


async def resolve_for_agent(db: AsyncSession, agent_id: uuid.UUID) -> FIMScope:
    """AGENT override wins over GLOBAL. Falls back to a synthetic /etc-only,
    version-0 scope if even the GLOBAL row is somehow missing — keeps this
    total rather than raising, since callers are on the heartbeat hot path."""
    agent_row = await get_agent_scope(db, agent_id)
    if agent_row is not None:
        return agent_row
    global_row = await get_global_scope(db)
    if global_row is not None:
        return global_row
    return FIMScope(
        scope_type="GLOBAL", watch_paths=["/etc"], ignore_paths=[],
        updated_at=datetime.now(timezone.utc),
    )


async def upsert_global_scope(
    db: AsyncSession, watch_paths: list, ignore_paths: list, updated_by: uuid.UUID | None
) -> FIMScope:
    watch_paths = _validate_paths(watch_paths, field="watch_paths", require_nonempty=True)
    ignore_paths = _validate_paths(ignore_paths, field="ignore_paths")
    row = await get_global_scope(db)
    now = datetime.now(timezone.utc)
    if row is None:
        row = FIMScope(
            scope_type="GLOBAL", watch_paths=watch_paths, ignore_paths=ignore_paths,
            updated_at=now, updated_by=updated_by,
        )
        db.add(row)
    else:
        row.watch_paths = watch_paths
        row.ignore_paths = ignore_paths
        row.updated_at = now
        row.updated_by = updated_by
    await db.flush()
    return row


async def upsert_agent_scope(
    db: AsyncSession, agent_id: uuid.UUID, watch_paths: list, ignore_paths: list,
    updated_by: uuid.UUID | None,
) -> FIMScope:
    watch_paths = _validate_paths(watch_paths, field="watch_paths", require_nonempty=True)
    ignore_paths = _validate_paths(ignore_paths, field="ignore_paths")
    row = await get_agent_scope(db, agent_id)
    now = datetime.now(timezone.utc)
    if row is None:
        row = FIMScope(
            scope_type="AGENT", agent_id=agent_id, watch_paths=watch_paths,
            ignore_paths=ignore_paths, updated_at=now, updated_by=updated_by,
        )
        db.add(row)
    else:
        row.watch_paths = watch_paths
        row.ignore_paths = ignore_paths
        row.updated_at = now
        row.updated_by = updated_by
    await db.flush()
    return row


async def delete_agent_scope(db: AsyncSession, agent_id: uuid.UUID) -> bool:
    row = await get_agent_scope(db, agent_id)
    if row is None:
        return False
    await db.delete(row)
    await db.flush()
    return True


def signed_envelope(agent_id: uuid.UUID, scope: FIMScope) -> dict:
    """Payload string is canonical_bytes(payload).decode() — the exact bytes
    sign_payload signs and the exact bytes the agent's VerifyFIMConfig
    ed25519-verifies. Never re-serialize scope on the agent side."""
    payload = {
        "agent_id": str(agent_id),
        "watch_paths": scope.watch_paths,
        "ignore_paths": scope.ignore_paths,
        "version": version_of(scope),
    }
    return {
        "payload": canonical_bytes(payload).decode(),
        "signature": sign_payload(payload),
        "signing_key_id": SIGNING_KEY_ID,
    }
