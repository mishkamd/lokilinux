"""Server side of snapshot signing (docs/security/SNAPSHOT_HMAC.md, P1r-3.1)."""

import base64
import json
import uuid

import pytest

from lokilinux.models.agent import Agent, AgentStatus
from lokilinux.services import snapshot_hmac
from lokilinux.services.agent_service import AgentService
from lokilinux.services.compliance_ingest_service import publish_domain_snapshots


def _agent() -> Agent:
    return Agent(agent_id=f"hmac-{uuid.uuid4().hex[:8]}", status=AgentStatus.ACTIVE, hostname="h")


def test_first_key_is_issued_once_and_is_32_bytes():
    agent = _agent()
    snapshot_hmac.ensure_key(agent)
    first = agent.snapshot_hmac_key
    assert agent.snapshot_hmac_key_id == 1
    assert len(base64.b64decode(first)) == 32

    snapshot_hmac.ensure_key(agent)
    assert agent.snapshot_hmac_key == first  # no-op once issued


def test_rotation_keeps_the_previous_key_for_verifying():
    agent = _agent()
    snapshot_hmac.ensure_key(agent)
    old = agent.snapshot_hmac_key

    snapshot_hmac.rotate(agent)

    assert agent.snapshot_hmac_key_id == 2
    assert agent.snapshot_hmac_key != old
    assert agent.snapshot_hmac_prev_key == old
    assert agent.snapshot_hmac_prev_key_id == 1


def test_key_is_sent_only_when_the_agent_is_stale():
    agent = _agent()
    assert snapshot_hmac.key_for_agent(agent, 0) is None  # no key issued yet

    snapshot_hmac.ensure_key(agent)
    assert snapshot_hmac.key_for_agent(agent, 1) is None  # already current
    sent = snapshot_hmac.key_for_agent(agent, 0)
    assert sent == {"key_id": 1, "key": agent.snapshot_hmac_key}


class _FakeNats:
    def __init__(self) -> None:
        self.published: list[tuple[str, dict]] = []

    async def publish(self, subject: str, data: bytes) -> None:
        self.published.append((subject, json.loads(data)))


@pytest.mark.asyncio
async def test_published_snapshot_carries_the_agents_mac():
    nats = _FakeNats()
    agent_id = uuid.uuid4()
    await publish_domain_snapshots(
        nats, agent_id,
        {"packages": {"x": 1}},
        {"packages": "h1"},
        {"packages": {"key_id": 3, "mac": "abc"}},
    )
    subject, msg = nats.published[0]
    assert subject == "lokilinux.compliance.snapshot.packages"
    assert msg["mac"] == "abc" and msg["key_id"] == 3
    assert msg["content_hash"] == "h1"


@pytest.mark.asyncio
async def test_snapshot_without_a_mac_is_published_unsigned():
    nats = _FakeNats()
    await publish_domain_snapshots(nats, uuid.uuid4(), {"packages": {}}, {"packages": "h1"})
    _, msg = nats.published[0]
    assert "mac" not in msg and "key_id" not in msg


@pytest.mark.asyncio
async def test_heartbeat_issues_a_key_to_an_agent_without_one(db_session, fake_cache):
    agent = _agent()
    db_session.add(agent)
    await db_session.flush()

    await AgentService(db_session, fake_cache).update_heartbeat(agent.agent_id, {})

    assert agent.snapshot_hmac_key is not None
    assert agent.snapshot_hmac_key_id == 1
