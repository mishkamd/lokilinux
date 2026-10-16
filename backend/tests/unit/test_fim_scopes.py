"""fim_scopes: resolution precedence, path validation, and the signed
envelope handed to agents — service-level tests, plus the agent-version
gate that decides whether the heartbeat attaches fim_config at all."""

import uuid

import pytest

from lokilinux.models.agent import Agent, AgentStatus
from lokilinux.services import fim_scope_service
from lokilinux.services.agent_policy_compiler import verify_signature, public_key_b64
from lokilinux.utils.agent_capability import MIN_AGENT_VERSION_FIM_SCOPES, agent_meets_minimum


async def _make_agent(db_session, **kwargs) -> Agent:
    agent = Agent(agent_id=f"agent-{uuid.uuid4()}", status=AgentStatus.ACTIVE, **kwargs)
    db_session.add(agent)
    await db_session.flush()
    return agent


@pytest.mark.asyncio
async def test_resolve_for_agent_falls_back_to_global(db_session):
    # Migration 044 seeds the one GLOBAL row (watch_paths=['/etc']) — no
    # per-agent override exists yet, so resolution must fall back to it.
    agent = await _make_agent(db_session)

    scope = await fim_scope_service.resolve_for_agent(db_session, agent.id)
    assert scope.scope_type == "GLOBAL"
    assert scope.watch_paths == ["/etc"]


@pytest.mark.asyncio
async def test_agent_override_wins_over_global(db_session):
    await fim_scope_service.upsert_global_scope(db_session, ["/etc"], [], None)
    agent = await _make_agent(db_session)
    await fim_scope_service.upsert_agent_scope(
        db_session, agent.id, ["/etc", "/opt/app/conf"], ["/etc/mtab"], None
    )
    await db_session.commit()

    scope = await fim_scope_service.resolve_for_agent(db_session, agent.id)
    assert scope.scope_type == "AGENT"
    assert scope.watch_paths == ["/etc", "/opt/app/conf"]
    assert scope.ignore_paths == ["/etc/mtab"]


@pytest.mark.asyncio
async def test_delete_agent_scope_reverts_to_global(db_session):
    await fim_scope_service.upsert_global_scope(db_session, ["/etc"], [], None)
    agent = await _make_agent(db_session)
    await fim_scope_service.upsert_agent_scope(db_session, agent.id, ["/opt/app"], [], None)
    await db_session.commit()

    deleted = await fim_scope_service.delete_agent_scope(db_session, agent.id)
    assert deleted is True
    await db_session.commit()

    scope = await fim_scope_service.resolve_for_agent(db_session, agent.id)
    assert scope.scope_type == "GLOBAL"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_paths",
    [
        ["relative/path"],
        ["/"],
        [123],
    ],
)
async def test_upsert_rejects_invalid_paths(db_session, bad_paths):
    with pytest.raises(fim_scope_service.FIMScopeValidationError):
        await fim_scope_service.upsert_global_scope(db_session, bad_paths, [], None)


@pytest.mark.asyncio
async def test_upsert_rejects_empty_watch_paths(db_session):
    # An override saved with zero watch paths would look configured in the
    # UI but SetPaths on the agent falls back to /etc for an empty list —
    # a silent no-op wearing an "override" label. Reset exists for that case.
    with pytest.raises(fim_scope_service.FIMScopeValidationError):
        await fim_scope_service.upsert_global_scope(db_session, [], ["/etc/mtab"], None)


@pytest.mark.asyncio
async def test_upsert_allows_empty_ignore_paths(db_session):
    row = await fim_scope_service.upsert_global_scope(db_session, ["/etc"], [], None)
    assert row.ignore_paths == []


@pytest.mark.asyncio
async def test_upsert_normalizes_dotdot_within_root(db_session):
    # "/etc/../root" can never escape above "/" on an absolute path —
    # normpath resolves it to a plain "/root", not a traversal attempt.
    row = await fim_scope_service.upsert_global_scope(db_session, ["/etc/../root"], [], None)
    assert row.watch_paths == ["/root"]


@pytest.mark.asyncio
async def test_upsert_rejects_too_many_paths(db_session):
    with pytest.raises(fim_scope_service.FIMScopeValidationError):
        await fim_scope_service.upsert_global_scope(
            db_session, [f"/path{i}" for i in range(65)], [], None
        )


@pytest.mark.asyncio
async def test_signed_envelope_verifies_with_platform_key(db_session, tmp_path, monkeypatch):
    monkeypatch.setenv("POLICY_SIGNING_KEY_PATH", str(tmp_path / "policy-signing.key"))
    agent = await _make_agent(db_session)
    row = await fim_scope_service.upsert_agent_scope(db_session, agent.id, ["/etc"], [], None)
    await db_session.commit()

    env = fim_scope_service.signed_envelope(agent.id, row)
    assert env["signing_key_id"] == "policy-signing-v1"

    import json

    payload = json.loads(env["payload"])
    assert payload["agent_id"] == str(agent.id)
    assert payload["watch_paths"] == ["/etc"]
    assert payload["version"] == fim_scope_service.version_of(row)

    assert verify_signature(payload, env["signature"], public_key_b64())


def test_agent_capability_gate():
    assert agent_meets_minimum("0.41.0", MIN_AGENT_VERSION_FIM_SCOPES) is True
    assert agent_meets_minimum("0.40.9", MIN_AGENT_VERSION_FIM_SCOPES) is False
    assert agent_meets_minimum(None, MIN_AGENT_VERSION_FIM_SCOPES) is False
