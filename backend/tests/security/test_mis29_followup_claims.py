"""MIS-29 follow-up: approval claims for multi-target jobs, and the key version
a claim is signed under.

(a) approving a 2-target job issues one ApprovalClaim per target agent, each
    bound to that agent's wire id;
(b) the selection the heartbeat uses hands each agent its own claim;
(c) a legacy claim with target_agent_id NULL is served only when no per-agent
    claim exists;
(d) the signing key comes from the versioned keys dir, and the claim verifies
    under the ACTIVE version's key.

Fixtures (db_session, fake_cache, fake_nats) come from tests/conftest.py.
"""

import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from sqlalchemy import select

from lokilinux.kms import KeyManager
from lokilinux.models.agent import Agent, AgentStatus
from lokilinux.models.approval import ApprovalClaim
from lokilinux.services.approval_claims import ClaimRejected, verify_claim
from lokilinux.services.job_service import JobService


def _pem(key: Ed25519PrivateKey) -> bytes:
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


def _pub(key_file: Path) -> Ed25519PublicKey:
    return serialization.load_pem_private_key(key_file.read_bytes(), password=None).public_key()


async def _make_agent(db_session) -> Agent:
    agent = Agent(
        agent_id=f"wire-{uuid.uuid4().hex[:8]}",
        status=AgentStatus.ACTIVE,
        hostname=f"host-{uuid.uuid4().hex[:8]}",
    )
    db_session.add(agent)
    await db_session.flush()
    return agent


async def _new_job(db_session, fake_cache, fake_nats, agents):
    svc = JobService(db_session, fake_cache, fake_nats)
    job = await svc.create_job(
        name="multi-target approval",
        job_type="SERVICE",
        target_servers={"agent_ids": [str(a.id) for a in agents]},
        parameters={"service_name": "nginx"},
        requires_approval=True,
     actor_role="ADMIN",)
    return svc, job


async def _claim_rows(db_session, job_id):
    return (
        (await db_session.execute(select(ApprovalClaim).where(ApprovalClaim.job_id == job_id)))
        .scalars()
        .all()
    )


@pytest.fixture()
def legacy_key(tmp_path, monkeypatch):
    """Legacy single-file job-signing key: the v1 seed, and the no-keys-dir layout."""
    key = Ed25519PrivateKey.generate()
    path = tmp_path / "job_signing.key"
    path.write_bytes(_pem(key))
    monkeypatch.setenv("JOB_SIGNING_KEY_PATH", str(path))
    monkeypatch.delenv("LOKILINUX_KEYS_DIR", raising=False)
    return path


@pytest.fixture()
def keys_dir_v1(legacy_key, tmp_path, monkeypatch):
    """Versioned keys dir with v1 registered and ACTIVE, as after bootstrap."""
    keys_dir = tmp_path / "keys"
    km = KeyManager(str(keys_dir), "job-signing")
    km.create(1, write_key_file=lambda p: Path(p).write_bytes(legacy_key.read_bytes()))
    km.activate(1)
    monkeypatch.setenv("LOKILINUX_KEYS_DIR", str(keys_dir))
    return keys_dir / "job-signing"


@pytest.fixture()
def rotated_keys(legacy_key, tmp_path, monkeypatch):
    """Versioned keys dir after a rotation: v1 VERIFY_ONLY, v2 ACTIVE."""
    keys_dir = tmp_path / "keys"
    km = KeyManager(str(keys_dir), "job-signing")
    km.create(1, write_key_file=lambda p: Path(p).write_bytes(legacy_key.read_bytes()))
    km.activate(1)
    v2 = Ed25519PrivateKey.generate()
    km.rotate(write_key_file=lambda p: Path(p).write_bytes(_pem(v2)))
    monkeypatch.setenv("LOKILINUX_KEYS_DIR", str(keys_dir))
    return keys_dir / "job-signing"


# ── (a) one claim per target agent ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_approving_two_target_job_issues_one_claim_per_agent(
    db_session, fake_cache, fake_nats, keys_dir_v1
):
    a = await _make_agent(db_session)
    b = await _make_agent(db_session)
    svc, job = await _new_job(db_session, fake_cache, fake_nats, [a, b])

    approved = await svc.approve_job(job.id, approved_by=None)

    rows = await _claim_rows(db_session, job.id)
    assert len(rows) == 2, "every target agent needs its own approval claim, not just the first"
    assert sorted(r.target_agent_id for r in rows) == sorted([a.agent_id, b.agent_id])

    pub = _pub(keys_dir_v1 / "v1.key")
    for row in rows:
        verify_claim(
            pub,
            json.loads(row.claim_json),
            expected_job_id=str(job.id),
            expected_payload=job.parameters,
            expected_target_agent_id=row.target_agent_id,
            required_capabilities=["SERVICE_CONTROL"],
        )
    # job.approval_claim_json keeps the first target's claim for existing callers
    assert json.loads(approved.approval_claim_json)["target_agent_id"] == a.agent_id


# ── (b) each agent is served its own claim ────────────────────────────────────


@pytest.mark.asyncio
async def test_each_agent_is_served_its_own_claim(
    db_session, fake_cache, fake_nats, keys_dir_v1
):
    from lokilinux.api.grpc.agent_service import _select_approval_claim

    a = await _make_agent(db_session)
    b = await _make_agent(db_session)
    svc, job = await _new_job(db_session, fake_cache, fake_nats, [a, b])
    await svc.approve_job(job.id, approved_by=None)

    got_a = await _select_approval_claim(db_session, job.id, a.agent_id)
    got_b = await _select_approval_claim(db_session, job.id, b.agent_id)
    assert got_a is not None and got_a.target_agent_id == a.agent_id
    assert got_b is not None and got_b.target_agent_id == b.agent_id

    # consumed_at is per row: consuming A's claim must not hide B's
    got_a.consumed_at = datetime.now(timezone.utc)
    await db_session.flush()
    assert await _select_approval_claim(db_session, job.id, a.agent_id) is None
    still_b = await _select_approval_claim(db_session, job.id, b.agent_id)
    assert still_b is not None and still_b.target_agent_id == b.agent_id


# ── (c) legacy NULL-target claim: fallback only ───────────────────────────────


@pytest.mark.asyncio
async def test_legacy_null_target_claim_served_only_without_per_agent_claim(
    db_session, fake_cache, fake_nats
):
    from lokilinux.api.grpc.agent_service import _select_approval_claim

    a = await _make_agent(db_session)
    b = await _make_agent(db_session)
    _, job = await _new_job(db_session, fake_cache, fake_nats, [a, b])

    expires = datetime.now(timezone.utc) + timedelta(minutes=5)
    legacy = ApprovalClaim(job_id=job.id, claim_json="{}", expires_at=expires)
    per_a = ApprovalClaim(
        job_id=job.id, target_agent_id=a.agent_id, claim_json="{}", expires_at=expires
    )
    db_session.add_all([legacy, per_a])
    await db_session.flush()

    got_a = await _select_approval_claim(db_session, job.id, a.agent_id)
    assert got_a is not None and got_a.id == per_a.id, "a per-agent claim wins over legacy"
    got_b = await _select_approval_claim(db_session, job.id, b.agent_id)
    assert got_b is not None and got_b.id == legacy.id, "legacy claim served when none is per-agent"


# ── (d) signing key version ───────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "versioned", [False, True], ids=["legacy-layout", "fresh-versioned-keys-dir"]
)
async def test_approval_issues_claim_on_legacy_and_fresh_keys_layouts(
    db_session, fake_cache, fake_nats, legacy_key, tmp_path, monkeypatch, versioned
):
    """Without a keys dir the legacy file is v1. With an empty keys dir the
    signer must bootstrap v1 from the legacy file, as the envelope signer does.
    Either way the approval must produce a claim the legacy key verifies."""
    keys_dir = tmp_path / "keys"
    if versioned:
        monkeypatch.setenv("LOKILINUX_KEYS_DIR", str(keys_dir))
    a = await _make_agent(db_session)
    svc, job = await _new_job(db_session, fake_cache, fake_nats, [a])

    await svc.approve_job(job.id, approved_by=None)

    rows = await _claim_rows(db_session, job.id)
    assert len(rows) == 1, "approval must not silently skip the claim on this key layout"
    verify_claim(
        _pub(legacy_key),
        json.loads(rows[0].claim_json),
        expected_job_id=str(job.id),
        expected_payload=job.parameters,
        expected_target_agent_id=a.agent_id,
        required_capabilities=["SERVICE_CONTROL"],
    )
    if versioned:
        assert KeyManager(str(keys_dir), "job-signing").active_version() == 1


@pytest.mark.asyncio
async def test_claim_is_signed_by_active_key_version(
    db_session, fake_cache, fake_nats, rotated_keys
):
    """After rotation the claim's signature must come from the ACTIVE key (v2).
    Verifying it under the superseded v1 key must fail."""
    a = await _make_agent(db_session)
    svc, job = await _new_job(db_session, fake_cache, fake_nats, [a])
    await svc.approve_job(job.id, approved_by=None)

    rows = await _claim_rows(db_session, job.id)
    assert len(rows) == 1
    claim = json.loads(rows[0].claim_json)
    bindings = dict(
        expected_job_id=str(job.id),
        expected_payload=job.parameters,
        expected_target_agent_id=a.agent_id,
        required_capabilities=["SERVICE_CONTROL"],
    )
    verify_claim(_pub(rotated_keys / "v2.key"), claim, **bindings)
    with pytest.raises(ClaimRejected) as ei:
        verify_claim(_pub(rotated_keys / "v1.key"), claim, **bindings)
    assert ei.value.reason == "bad_signature"


@pytest.mark.asyncio
async def test_claim_key_version_field_names_the_active_version(
    db_session, fake_cache, fake_nats, rotated_keys
):
    a = await _make_agent(db_session)
    svc, job = await _new_job(db_session, fake_cache, fake_nats, [a])
    await svc.approve_job(job.id, approved_by=None)

    rows = await _claim_rows(db_session, job.id)
    assert json.loads(rows[0].claim_json)["key_version"] == 2
