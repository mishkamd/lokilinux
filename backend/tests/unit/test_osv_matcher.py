"""Debian/Ubuntu CVE matching through OSV (ROADMAP R4). OSV is mocked with httpx.MockTransport."""

import json
import uuid

import httpx
import pytest
from sqlalchemy import select

from lokilinux.models.agent import Agent, AgentStatus
from lokilinux.models.cve import CVE, AgentVulnerability, Package
from lokilinux.services.osv_matcher import cve_ids_from_osv, ecosystem_for, match_packages

BASE = "https://osv.test"


def test_ecosystem_mapping():
    assert ecosystem_for("debian", "12") == "Debian:12"
    assert ecosystem_for("debian", "12.5") == "Debian:12"
    assert ecosystem_for("ubuntu", "22.04") == "Ubuntu:22.04:LTS"
    assert ecosystem_for("ubuntu", "23.10") == "Ubuntu:23.10"
    assert ecosystem_for("rocky", "9.8") is None
    assert ecosystem_for("debian", None) is None


def test_cve_ids_from_osv_keeps_only_cve_ids():
    ids = ["DEBIAN-CVE-2023-5363", "UBUNTU-CVE-2024-1111", "DSA-5555-1", "CVE-2020-1"]
    assert cve_ids_from_osv(ids) == {"CVE-2023-5363", "CVE-2024-1111", "CVE-2020-1"}


def _key(query: dict) -> tuple[str, str]:
    return query["package"]["name"], query["version"]


def _osv(vulns_by_pkg: dict) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path != "/v1/querybatch":
            return httpx.Response(404)
        body = json.loads(request.content)
        results = [
            {"vulns": [{"id": i} for i in vulns_by_pkg.get(_key(q), [])]}
            for q in body["queries"]
        ]
        return httpx.Response(200, json={"results": results})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


LIBSSL = "3.0.11-1~deb12u1"


def _libssl_row(agent_id) -> Package:
    return Package(agent_id=agent_id, name="libssl3", version=LIBSSL, source_package="openssl")


async def _debian_agent(db_session) -> Agent:
    agent = Agent(
        agent_id=f"deb-{uuid.uuid4().hex[:8]}", status=AgentStatus.ACTIVE,
        hostname=f"deb-{uuid.uuid4().hex[:6]}", os_distro="debian", os_version="12",
    )
    db_session.add(agent)
    await db_session.flush()
    return agent


@pytest.mark.asyncio
async def test_library_matched_through_its_source_package(db_session):
    agent = await _debian_agent(db_session)
    db_session.add(_libssl_row(agent.id))
    await db_session.flush()

    client = _osv({("openssl", LIBSSL): ["DEBIAN-CVE-2023-5363"]})
    try:
        await match_packages(db_session, client, base_url=BASE)
    finally:
        await client.aclose()

    rows = (await db_session.execute(
        select(AgentVulnerability).where(AgentVulnerability.agent_id == agent.id)
    )).scalars().all()
    assert [(r.cve_id, r.package_name) for r in rows] == [("CVE-2023-5363", "libssl3")]


@pytest.mark.asyncio
async def test_rows_for_old_package_versions_are_removed(db_session):
    agent = await _debian_agent(db_session)
    db_session.add(_libssl_row(agent.id))
    db_session.add(CVE(cve_id="CVE-2020-0001"))
    await db_session.flush()  # the CVE row first: AgentVulnerability refers to it by FK only
    db_session.add(AgentVulnerability(
        agent_id=agent.id, cve_id="CVE-2020-0001",
        package_name="libssl3", package_version="3.0.10-1",
    ))
    await db_session.flush()

    client = _osv({})
    try:
        await match_packages(db_session, client, base_url=BASE)
    finally:
        await client.aclose()

    rows = (await db_session.execute(
        select(AgentVulnerability).where(AgentVulnerability.agent_id == agent.id)
    )).scalars().all()
    assert rows == []
