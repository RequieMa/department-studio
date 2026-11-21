from tests.test_api import http_app as http_app
from tests.test_api import lead_body


async def test_hierarchy_api_defaults_to_complete_and_toggles_edges(http_app, tmp_path):
    client, _, _ = http_app
    leads = []
    for handle in ("alpha", "beta", "gamma"):
        response = await client.post(
            "/api/leads", json=lead_body(tmp_path, handle=handle, name=handle.title())
        )
        assert response.status_code == 201
        leads.append(response.json())
    graph = (await client.get("/api/hierarchy")).json()
    assert {node["handle"] for node in graph["nodes"]} == {"alpha", "beta", "gamma"}
    assert len(graph["edges"]) == 3
    first, second, third = (lead["id"] for lead in leads)
    response = await client.put(
        "/api/hierarchy/edges",
        json={"a": first, "b": second, "connected": False},
    )
    assert response.status_code == 200
    assert len(response.json()["edges"]) == 2
    assert {
        (edge["a"], edge["b"]) for edge in (await client.get("/api/hierarchy")).json()["edges"]
    } == {
        (min(first, third), max(first, third)),
        (min(second, third), max(second, third)),
    }
    response = await client.put(
        "/api/hierarchy/edges",
        json={"a": second, "b": first, "connected": True},
    )
    assert len(response.json()["edges"]) == 3
    response = await client.post("/api/hierarchy/connect-all")
    assert len(response.json()["edges"]) == 3
    assert (
        await client.put(
            "/api/hierarchy/edges",
            json={"a": first, "b": first, "connected": True},
        )
    ).status_code == 422
    assert (await client.get("/api/hierarchy", headers={"Authorization": ""})).status_code == 401
