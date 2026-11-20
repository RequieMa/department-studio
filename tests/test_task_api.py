import json

from tests.fakes import until
from tests.test_api import http_app as http_app
from tests.test_api import lead_body


async def setup_task(client, tmp_path):
    lead = (await client.post("/api/leads", json=lead_body(tmp_path))).json()
    await client.post("/api/messages", json={"text": "@atlas original"})
    task = (await client.get("/api/tasks")).json()["tasks"][0]
    return lead, task


async def test_task_http_contract_strict_owner_only_and_safe_errors(http_app, tmp_path):
    client, app, backend = http_app
    lead, task = await setup_task(client, tmp_path)
    path = f"/api/tasks/{task['id']}"
    assert "tasks" not in (await client.get("/api/state")).json()
    body = {
        "text": "Follow @all literally",
        "task_revision": 1,
        "idempotency_key": "follow",
        "mode": "execute",
    }
    paused = await client.post(path + "/instructions", json=body)
    assert paused.status_code == 409 and paused.json()["code"] == "room_paused"
    for changes in (
        {"task_revision": True},
        {"task_revision": "1"},
        {"mode": "steer"},
        {"owner_lead_id": lead["id"]},
        {"text": "   "},
    ):
        result = await client.post(path + "/instructions", json=body | changes)
        assert result.status_code == 422
    assert (await client.get("/api/tasks/missing")).status_code == 404
    for query in ("cursor=-1", "limit=201", "limit=0"):
        assert (await client.get("/api/tasks?" + query)).status_code == 422
    await client.post("/api/room/resume")
    queued = await client.post(path + "/instructions", json=body)
    assert queued.status_code == 201
    await until(lambda: backend.requests)
    runtime = {"Authorization": "Bearer " + backend.requests[0].bridge_token}
    routes = [
        ("GET", "/api/tasks"),
        ("GET", path),
        ("POST", "/api/tasks"),
        ("PATCH", path),
        ("POST", path + "/instructions"),
        ("GET", "/api/action-requests"),
        ("POST", path + "/action-requests"),
        ("POST", "/api/action-requests/missing/resolve"),
    ]
    for method, route in routes:
        for headers, status in (
            ({"Authorization": ""}, 401),
            (runtime, 403),
            ({"Origin": "https://evil.example"}, 403),
        ):
            response = await client.request(method, route, json={}, headers=headers)
            assert response.status_code == status
    assert (await client.post(path + "/instructions", json=body)).json() == queued.json()
    details = (await client.get(path)).json()
    assert details["instructions"][0]["delivery_state"] == "running"
    assert details["messages"][-1]["recipient_ids"] == [lead["id"]]
    serialized = json.dumps(details)
    for secret in (
        "bridge_token",
        "native_session_ref",
        "conversation_id",
        runtime["Authorization"],
    ):
        assert secret not in serialized
    assert app.state.store.list_action_requests()["action_requests"] == []


async def test_child_edit_stale_retry_and_decision_resolution_http(http_app, tmp_path):
    client, _, _ = http_app
    lead, task = await setup_task(client, tmp_path)
    args = {
        "parent_id": task["id"],
        "parent_revision": 1,
        "owner_lead_id": lead["id"],
        "title": "Child <script>",
        "context": "durable",
        "idempotency_key": "child",
    }
    child = (await client.post("/api/tasks", json=args)).json()
    path = f"/api/tasks/{child['id']}"
    patch = await client.patch(path, json={"task_revision": 1, "context": "edited"})
    assert patch.status_code == 200 and patch.json()["revision"] == 2
    assert (await client.post("/api/tasks", json=args)).json() == child
    assert (await client.patch(path, json={"task_revision": 1, "title": "stale"})).json()[
        "code"
    ] == "stale_task"
    assert (
        await client.patch(path, json={"task_revision": 2, "owner_lead_id": lead["id"]})
    ).status_code == 422
    decision = {
        "question": "Choose one",
        "options": [{"id": "a", "label": "Alpha"}, {"id": "b", "label": "Beta"}],
        "task_revision": 2,
        "idempotency_key": "ask",
    }
    request = await client.post(path + "/action-requests", json=decision)
    assert request.status_code == 201
    request_id = request.json()["id"]
    assert len((await client.get("/api/action-requests")).json()["action_requests"]) == 1
    resolve = f"/api/action-requests/{request_id}/resolve"
    choice = {
        "option_id": "b",
        "revision": 1,
        "task_revision": 2,
        "idempotency_key": "choose",
        "mode": "execute",
    }
    assert (await client.post(resolve, json=choice)).json()["code"] == "room_paused"
    assert len((await client.get("/api/action-requests")).json()["action_requests"]) == 1
    choice["mode"] = "record_note"
    result = await client.post(resolve, json=choice)
    assert result.status_code == 200
    assert result.json()["instruction"]["delivery_id"] is None
    assert (await client.post(resolve, json=choice)).json() == result.json()
    assert (await client.get("/api/action-requests")).json()["action_requests"] == []
    assert (await client.get("/api/state")).json()["deliveries"] == []
