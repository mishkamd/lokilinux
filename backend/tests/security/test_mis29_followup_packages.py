"""MIS-29 follow-up — package names from the heartbeat's package report.

_sync_packages stored every agent-reported name verbatim. osv_matcher reads
those names back from the Package table and turns them into
AgentVulnerability rows, so a name with shell syntax reached the CVE path.
Pre-fix, all three names below are stored, so the row assertion fails.
"""

import uuid

import pytest
from sqlalchemy import select

from lokilinux.models.agent import Agent, AgentStatus
from lokilinux.models.cve import Package
from lokilinux.services.agent_service import AgentService


@pytest.mark.asyncio
async def test_package_report_stores_only_valid_names(db_session, fake_cache, tmp_path):
    agent = Agent(
        agent_id=f"mis29-pkg-{uuid.uuid4().hex[:8]}",
        status=AgentStatus.ACTIVE,
        hostname="h-pkg",
    )
    db_session.add(agent)
    await db_session.flush()
    sentinel = tmp_path / "SENTINEL"

    await AgentService(db_session, fake_cache).update_heartbeat(
        agent.agent_id,
        {
            "packages": [
                {"name": name, "version": "1.0"}
                for name in ["openssl", "pkg; rm -rf /", f"x$(touch {sentinel})"]
            ]
        },
    )

    names = (
        (await db_session.execute(select(Package.name).where(Package.agent_id == agent.id)))
        .scalars()
        .all()
    )
    assert names == ["openssl"]
    assert not sentinel.exists()
