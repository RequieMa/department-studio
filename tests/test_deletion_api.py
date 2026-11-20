import pytest

from tests.fakes import until
from tests.test_api import http_app as http_app
from tests.test_api import lead_body


async def test_delete_contract_retry_history_and_tombstone_patch(http_app, tmp_path):
    client, app, _ = http_app
    lead = (await client.post("/api/leads", json=lead_body(tmp_path))).json()
    disabled = (
        await client.post("/api/leads", json=lead_body(tmp_path, handle="disabled", enabled=False))
    ).json()
    app.state.store.post_public_reply(lead["id"], "Historical")
    before = (await client.get("/api/state")).json()
    response = await client.delete(
        f"/api/leads/{lead['id']}", params={"revision": lead["revision"]}
    )
    assert response.status_code == 200
    receipt = response.json()
    assert set(receipt) == {"id", "revision", "deleted_at"}
    assert receipt["id"] == lead["id"] and receipt["revision"] == lead["revision"] + 1
    assert isinstance(receipt["deleted_at"], str)
    repeat = await client.delete(f"/api/leads/{lead['id']}", params={"revision": lead["revision"]})
    assert repeat.status_code == 200 and repeat.json() == receipt
    state = (await client.get("/api/state")).json()
    assert state["leads"] == [disabled]
    assert state["messages"] == before["messages"] and state["deliveries"] == before["deliveries"]
    assert (
        await client.patch(
            f"/api/leads/{lead['id']}", json=lead_body(tmp_path, revision=receipt["revision"])
        )
    ).status_code == 404
    assert (await client.post("/api/messages", json={"text": "@atlas work"})).status_code == 422
    assert (
        await client.post("/api/leads", json=lead_body(tmp_path, handle="ATLAS"))
    ).status_code == 409
    assert (await client.delete("/api/leads/missing", params={"revision": 1})).status_code == 404


@pytest.mark.parametrize(
    "query",
    [
        "",
        "?revision=0",
        "?revision=-1",
        "?revision=true",
        "?revision=1.5",
        "?revision=1.0",
        "?revision=abc",
        "?revision=",
        "?revision=1&revision=2",
    ],
)
async def test_delete_invalid_revision_is_422_and_does_not_mutate(http_app, tmp_path, query):
    client, _, _ = http_app
    lead = (await client.post("/api/leads", json=lead_body(tmp_path))).json()
    response = await client.delete(f"/api/leads/{lead['id']}" + query)
    assert response.status_code == 422
    assert (await client.get("/api/state")).json()["leads"] == [lead]


async def test_delete_revision_busy_and_unchanged_credential_boundary(http_app, tmp_path):
    client, app, backend = http_app
    lead = (await client.post("/api/leads", json=lead_body(tmp_path))).json()
    target = (await client.post("/api/leads", json=lead_body(tmp_path, handle="target"))).json()
    path = f"/api/leads/{target['id']}?revision={target['revision']}"
    assert (await client.delete(path, headers={"Authorization": ""})).status_code == 401
    assert (
        await client.delete(path, headers={"Origin": "https://evil.example"})
    ).status_code == 403
    assert (await client.delete(f"/api/leads/{target['id']}?revision=999")).status_code == 409
    await client.post("/api/room/resume")
    await client.post("/api/messages", json={"text": "@atlas work"})
    await until(lambda: backend.requests)
    run = backend.requests[0]
    runtime = {"Authorization": "Bearer " + run.bridge_token}
    assert (await client.delete(path, headers=runtime)).status_code == 403
    assert app.state.store.get_lead(target["id"]).revision == target["revision"]
    assert (await client.delete(f"/api/leads/{lead['id']}?revision=1")).status_code == 409
    backend.cancel_mode = "refuse"
    await client.post("/api/room/pause")
    assert (await client.delete(f"/api/leads/{lead['id']}?revision=1")).status_code == 409
    backend.release(run, text="late")
    await until(lambda: app.state.store.get_delivery(run.id).state == "interrupted")
    assert (await client.delete(f"/api/leads/{lead['id']}?revision=1")).status_code == 200
    assert (
        await client.post(
            "/api/bridge/messages", json={"call_id": "late", "text": "late"}, headers=runtime
        )
    ).status_code == 409
