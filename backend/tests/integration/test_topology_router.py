import pytest


@pytest.mark.asyncio
async def test_get_graph_empty(client):
    resp = await client.get("/api/v1/topology")
    assert resp.status_code == 200
    assert resp.json() == {"nodes": [], "edges": []}


@pytest.mark.asyncio
async def test_create_node_and_see_it_in_graph(client):
    resp = await client.post("/api/v1/topology/nodes", json={"kind": "HOST", "name": "web-1"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["kind"] == "HOST"
    assert body["name"] == "web-1"

    graph = await client.get("/api/v1/topology")
    assert len(graph.json()["nodes"]) == 1


@pytest.mark.asyncio
async def test_create_edge_and_delete_it(client):
    a = (await client.post("/api/v1/topology/nodes", json={"kind": "APPLICATION", "name": "app"})).json()
    b = (await client.post("/api/v1/topology/nodes", json={"kind": "SERVICE", "name": "svc"})).json()

    edge_resp = await client.post("/api/v1/topology/edges", json={"from_node": a["id"], "to_node": b["id"]})
    assert edge_resp.status_code == 201

    graph = (await client.get("/api/v1/topology")).json()
    assert len(graph["edges"]) == 1

    del_resp = await client.request(
        "DELETE", "/api/v1/topology/edges", params={"from_node": a["id"], "to_node": b["id"]}
    )
    assert del_resp.status_code == 204

    graph_after = (await client.get("/api/v1/topology")).json()
    assert graph_after["edges"] == []


@pytest.mark.asyncio
async def test_create_node_rejects_unknown_fields(client):
    resp = await client.post("/api/v1/topology/nodes", json={"kind": "HOST", "name": "x", "bogus": "field"})
    assert resp.status_code == 422
