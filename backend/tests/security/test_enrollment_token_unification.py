"""Regression test for the enrollment-token dual-system bug (agent-policy-
modernization plan Phase 3 / gap-closure plan P0): a token issued through
the DB-backed admin API (POST /agent-policies/enrollment-tokens) must
actually be able to enroll an agent through POST /agents/register — before
this fix, the register endpoint only ever checked the Redis TTL-only store,
so a token minted through the new UI/API silently could never be used.
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from lokilinux.models.agent import Agent
from lokilinux.models.agent_policy import AgentGroup, EnrollmentToken


def _register_body(hostname: str) -> dict:
    return {"hostname": hostname, "os_distro": "rocky", "os_version": "9.8", "arch": "amd64"}


@pytest.mark.asyncio
async def test_token_from_plural_api_enrolls_an_agent(client: AsyncClient):
    issue_resp = await client.post(
        "/api/v1/agent-policies/enrollment-tokens",
        json={"label": "test", "ttl_hours": 24, "single_use": True},
    )
    assert issue_resp.status_code == 200
    token = issue_resp.json()["token"]

    reg_resp = await client.post(
        "/api/v1/agents/register",
        json=_register_body(f"host-{uuid.uuid4().hex[:8]}"),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert reg_resp.status_code == 200
    assert reg_resp.json()["agent_id"]


@pytest.mark.asyncio
async def test_same_token_survives_download_then_registers(client: AsyncClient):
    """The offline installer spends ONE token on two sequential calls
    (download the binary, then register) — download must not burn a
    single-use token before register gets to use it."""
    issue_resp = await client.post(
        "/api/v1/agent-policies/enrollment-tokens",
        json={"label": "test", "ttl_hours": 24, "single_use": True},
    )
    token = issue_resp.json()["token"]

    dl_resp = await client.get(
        "/api/v1/agent/download",
        params={"os": "tar.gz", "arch": "amd64"},
        headers={"Authorization": f"Bearer {token}"},
    )
    # 503 (binary not built in this test env) proves the token was accepted
    # (403 would mean it got rejected/consumed) — not a real download.
    assert dl_resp.status_code in (200, 503)

    reg_resp = await client.post(
        "/api/v1/agents/register",
        json=_register_body(f"host-{uuid.uuid4().hex[:8]}"),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert reg_resp.status_code == 200


@pytest.mark.asyncio
async def test_single_use_token_rejected_on_second_register(client: AsyncClient):
    issue_resp = await client.post(
        "/api/v1/agent-policies/enrollment-tokens",
        json={"label": "test", "ttl_hours": 24, "single_use": True},
    )
    token = issue_resp.json()["token"]

    first = await client.post(
        "/api/v1/agents/register",
        json=_register_body(f"host-{uuid.uuid4().hex[:8]}"),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert first.status_code == 200

    second = await client.post(
        "/api/v1/agents/register",
        json=_register_body(f"host-{uuid.uuid4().hex[:8]}"),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert second.status_code == 403


@pytest.mark.asyncio
async def test_revoked_token_rejected(client: AsyncClient):
    issue_resp = await client.post(
        "/api/v1/agent-policies/enrollment-tokens",
        json={"label": "test", "ttl_hours": 24, "single_use": True},
    )
    token_id = issue_resp.json()["id"]
    token = issue_resp.json()["token"]

    revoke_resp = await client.delete(f"/api/v1/agent-policies/enrollment-tokens/{token_id}")
    assert revoke_resp.status_code == 200

    reg_resp = await client.post(
        "/api/v1/agents/register",
        json=_register_body(f"host-{uuid.uuid4().hex[:8]}"),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert reg_resp.status_code == 403


@pytest.mark.asyncio
async def test_expired_token_rejected(client: AsyncClient, db_session):
    from datetime import datetime, timedelta, timezone

    from lokilinux.services.agent_policies import AgentPolicyService

    plaintext = "expired-token-plaintext"
    db_session.add(
        EnrollmentToken(
            token_hash=AgentPolicyService.hash_token(plaintext),
            label="expired",
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
            single_use=True,
        )
    )
    await db_session.commit()

    reg_resp = await client.post(
        "/api/v1/agents/register",
        json=_register_body(f"host-{uuid.uuid4().hex[:8]}"),
        headers={"Authorization": f"Bearer {plaintext}"},
    )
    assert reg_resp.status_code == 403


@pytest.mark.asyncio
async def test_group_bound_token_stamps_agent_group_id(client: AsyncClient, db_session):
    group = AgentGroup(name="test-group")
    db_session.add(group)
    await db_session.commit()

    issue_resp = await client.post(
        "/api/v1/agent-policies/enrollment-tokens",
        json={"label": "test", "ttl_hours": 24, "single_use": True, "agent_group": str(group.id)},
    )
    assert issue_resp.status_code == 200
    token = issue_resp.json()["token"]

    hostname = f"host-{uuid.uuid4().hex[:8]}"
    reg_resp = await client.post(
        "/api/v1/agents/register",
        json=_register_body(hostname),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert reg_resp.status_code == 200

    row = (await db_session.execute(select(Agent).where(Agent.hostname == hostname))).scalar_one()
    assert row.agent_group_id == group.id


@pytest.mark.asyncio
async def test_missing_token_rejected(client: AsyncClient):
    reg_resp = await client.post("/api/v1/agents/register", json=_register_body("no-token-host"))
    assert reg_resp.status_code == 401


@pytest.mark.asyncio
async def test_unknown_token_rejected(client: AsyncClient):
    reg_resp = await client.post(
        "/api/v1/agents/register",
        json=_register_body("bad-token-host"),
        headers={"Authorization": "Bearer this-token-does-not-exist"},
    )
    assert reg_resp.status_code == 403
