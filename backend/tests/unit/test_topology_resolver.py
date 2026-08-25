from uuid import uuid4

import pytest

from lokilinux.models.agent import Agent, AgentStatus
from lokilinux.topology.models import TopologyNode
from lokilinux.topology.service import add_edge, downstream, ensure_host_node, remove_edge, upstream


async def _make_node(db_session, *, kind: str, name: str) -> TopologyNode:
    node = TopologyNode(tenant_id="default", kind=kind, name=name)
    db_session.add(node)
    await db_session.flush()
    return node


async def _make_agent(db_session, *, hostname: str) -> Agent:
    agent = Agent(agent_id=str(uuid4()), status=AgentStatus.ACTIVE, hostname=hostname)
    db_session.add(agent)
    await db_session.flush()
    return agent


@pytest.mark.asyncio
async def test_ensure_host_node_creates_once(db_session):
    agent = await _make_agent(db_session, hostname="web-1")
    first = await ensure_host_node(db_session, agent_id=agent.id, hostname="web-1")
    second = await ensure_host_node(db_session, agent_id=agent.id, hostname="web-1")
    assert first.id == second.id


@pytest.mark.asyncio
async def test_ensure_host_node_different_hostnames_are_different_nodes(db_session):
    agent_a = await _make_agent(db_session, hostname="web-1")
    agent_b = await _make_agent(db_session, hostname="web-2")
    a = await ensure_host_node(db_session, agent_id=agent_a.id, hostname="web-1")
    b = await ensure_host_node(db_session, agent_id=agent_b.id, hostname="web-2")
    assert a.id != b.id


@pytest.mark.asyncio
async def test_upstream_follows_dependency_chain(db_session):
    app_node = await _make_node(db_session, kind="APPLICATION", name="checkout")
    db_node = await _make_node(db_session, kind="SERVICE", name="postgres")
    host_node = await _make_node(db_session, kind="HOST", name="db-1")

    await add_edge(db_session, app_node.id, db_node.id)
    await add_edge(db_session, db_node.id, host_node.id)

    deps = await upstream(db_session, app_node.id)
    names = {d["name"] for d in deps}
    assert names == {"postgres", "db-1"}  # both direct and transitive


@pytest.mark.asyncio
async def test_downstream_follows_impact_chain(db_session):
    app_node = await _make_node(db_session, kind="APPLICATION", name="checkout")
    db_node = await _make_node(db_session, kind="SERVICE", name="postgres")
    host_node = await _make_node(db_session, kind="HOST", name="db-1")

    await add_edge(db_session, app_node.id, db_node.id)
    await add_edge(db_session, db_node.id, host_node.id)

    impacted = await downstream(db_session, host_node.id)
    names = {d["name"] for d in impacted}
    assert names == {"postgres", "checkout"}  # everything that (transitively) depends on db-1


@pytest.mark.asyncio
async def test_depth_cap_limits_traversal(db_session):
    nodes = [await _make_node(db_session, kind="SERVICE", name=f"svc-{i}") for i in range(8)]
    for a, b in zip(nodes, nodes[1:]):
        await add_edge(db_session, a.id, b.id)

    deps = await upstream(db_session, nodes[0].id, max_depth=2)
    assert len(deps) == 2  # svc-1, svc-2 only — svc-3.. are past the cap


@pytest.mark.asyncio
async def test_isolated_node_has_no_dependencies_or_impact(db_session):
    node = await _make_node(db_session, kind="HOST", name="lonely-host")
    assert await upstream(db_session, node.id) == []
    assert await downstream(db_session, node.id) == []


@pytest.mark.asyncio
async def test_remove_edge_breaks_the_chain(db_session):
    a = await _make_node(db_session, kind="APPLICATION", name="a")
    b = await _make_node(db_session, kind="SERVICE", name="b")
    await add_edge(db_session, a.id, b.id)
    assert len(await upstream(db_session, a.id)) == 1

    await remove_edge(db_session, a.id, b.id)
    assert await upstream(db_session, a.id) == []
