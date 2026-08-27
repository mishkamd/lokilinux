"""Heartbeat policy loop tests — envelope attach + report handling.

Focused on the two helpers in services/agent_policy_service.py:
  _pending_policy_envelope : pending deployment → wire envelope (delivered)
  _apply_policy_report     : agent's apply outcome → deployments + agents row
"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from lokilinux.services import agent_policy_service as aps
from lokilinux.models.agent_policy import DeploymentStatus


def _version(**overrides):
    base = dict(
        policy_id="11111111-1111-1111-1111-111111111111",
        version=2,
        signature="sig",
        payload_hash="abc123",
        signing_key_id="policy-signing-v1",
        status="published",
        id="22222222-2222-2222-2222-222222222222",
        payload={"apiVersion": "lokilinux.io/v1"},
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _deployment(**overrides):
    base = dict(
        agent_id="agent-a", version_id="22222222-2222-2222-2222-222222222222",
        status="pending", started_at=None, error=None,
        id="dep-1", finished_at=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _db(get_models=None, select_result=None):
    """AsyncSession stand-in: get(cls,key) → table lookup; execute(q) →
    canned scalar result."""
    db = MagicMock()

    async def get_model(cls, key):
        if get_models and cls.__name__ in get_models:
            return get_models[cls.__name__]
        return None

    db.get = get_model

    async def execute(q):
        res = MagicMock()
        scalars = MagicMock()
        if select_result is not None:
            many = select_result if isinstance(select_result, list) else [select_result]
            scalars.all.return_value = many
        else:
            scalars.all.return_value = []
        # Result-level AND Scalars-level accessors both route to the same row
        res.scalars.return_value = scalars
        if select_result is not None:
            res.scalar_one_or_none = lambda: select_result
            scalars.scalar_one_or_none = lambda: select_result
        else:
            res.scalar_one_or_none = lambda: None
            scalars.scalar_one_or_none = lambda: None
        return res

    db.execute = execute
    return db


def _agent():
    return SimpleNamespace(
        id="agent-a",
        agent_id="identity-abc",
        current_policy_version_id=None,
        desired_policy_version_id="22222222-2222-2222-2222-222222222222",
        policy_status="syncing",
        policy_last_error=None,
    )


@pytest.mark.asyncio
async def test_pending_envelope_delivered_marks_syncing():
    version = _version()
    deployment = _deployment()
    db = _db({"AgentPolicyVersion": version}, deployment)
    cache = MagicMock()
    cache.invalidate_pattern = AsyncMock()
    agent = _agent()

    out = await aps._pending_policy_envelope(db, agent)

    assert out is not None
    assert out["deployment_id"] == "dep-1"
    assert deployment.status == "delivered"
    assert agent.policy_status == "syncing"
    # wire contract: payload travels as canonical STRING bytes
    assert isinstance(out["payload"], str)
    # and the string itself IS canonical JSON (sorted keys, compact)
    parsed = json.loads(out["payload"])
    assert json.dumps(parsed, sort_keys=True, separators=(",", ":")) == out["payload"]


@pytest.mark.asyncio
async def test_no_pending_deployment_returns_none():
    db = _db(select_result=None)
    out = await aps._pending_policy_envelope(db, _agent())
    assert out is None


@pytest.mark.asyncio
async def test_apply_report_marks_applied_and_sets_actual_version():
    deployment = _deployment(status="delivered")
    version = _version(policy_id="p-1")
    agent = _agent()

    db = _db(
        {"AgentPolicyVersion": version},
        select_result=[deployment],  # _apply_policy_report lists recent deployments
    )
    cache = MagicMock()
    cache.invalidate_pattern = AsyncMock()

    report = {
        "policy_id": "p-1",
        "version": 2,
        "result": "applied",
        "duration_ms": 42,
        "deployment_id": "dep-1",
    }
    await aps._apply_policy_report(db, agent, cache, report)

    assert deployment.status == "applied"
    assert deployment.finished_at is not None
    assert agent.policy_status == "idle"
    assert agent.current_policy_version_id == version.id
    assert cache.invalidate_pattern.await_count >= 1


@pytest.mark.asyncio
async def test_apply_failure_freezes_desired_at_last_good():
    deployment = _deployment(status="delivered")
    version = _version(policy_id="p-1")
    agent = _agent()

    db = _db(
        {"AgentPolicyVersion": version},
        select_result=[deployment],
    )
    cache = MagicMock()
    cache.invalidate_pattern = AsyncMock()

    report = {
        "policy_id": "p-1", "version": 2, "result": "failed",
        "error": "[bad_signature] ed25519 verification failed",
        "deployment_id": "dep-1",
    }
    await aps._apply_policy_report(db, agent, cache, report)

    assert deployment.status == "failed"
    assert "bad_signature" in deployment.error
    assert agent.policy_status == "failed"
    # desired freezes at last-good so we don't re-push the broken doc forever
    assert agent.desired_policy_version_id == agent.current_policy_version_id
