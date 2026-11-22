import pytest

from department_studio.backends.base import ContextOutcome
from tests.fakes import until
from tests.test_api import http_app as http_app
from tests.test_api import lead_body
from tests.test_context_resume import ContextBackend


async def test_resume_returns_progress_and_owner_can_cancel_without_running_work(
    http_app, tmp_path
):
    client, app, _ = http_app
    backend = ContextBackend()
    app.state.service.backend = backend
    lead = (await client.post("/api/leads", json=lead_body(tmp_path))).json()
    response = await client.post("/api/room/resume")
    assert response.status_code == 200
    assert response.json()["paused"] and response.json()["preparing"]
    await until(lambda: backend.checks)
    response = await client.post("/api/room/resume")
    assert response.status_code == 200 and len(backend.checks) == 1
    progress = (await client.get("/api/state")).json()
    assert progress["context_checks"][0]["state"] == "compacting"
    assert progress["leads"][0]["status"] == "preparing"
    assert (
        await client.post("/api/leads", json=lead_body(tmp_path, handle="other"))
    ).status_code == 409
    assert (await client.delete(f"/api/leads/{lead['id']}?revision=1")).status_code == 409
    assert (
        await client.patch(f"/api/leads/{lead['id']}", json=lead_body(tmp_path, revision=1))
    ).status_code == 409
    receipt = (
        await client.post("/api/messages", json={"text": "@atlas note while preparing"})
    ).json()
    assert receipt["recipient_ids"] == []
    await client.post("/api/room/pause")
    await until(lambda: not backend.context_active)
    state = (await client.get("/api/state")).json()
    assert state["paused"] and not state["preparing"]
    assert state["context_checks"][0]["state"] == "interrupted"
    assert state["leads"][0]["conversation_id"] == lead["conversation_id"]
    assert not backend.requests and not state["deliveries"]


@pytest.mark.parametrize("action", ["reset", "failed"])
async def test_resume_result_is_visible_and_changes_only_conversation_when_needed(
    http_app, tmp_path, action
):
    client, app, backend = http_app

    async def prepare(request, emit):
        return ContextOutcome(action, native_session_ref="/retained/native.jsonl")

    backend.prepare_context = prepare
    lead = (await client.post("/api/leads", json=lead_body(tmp_path))).json()
    await client.post("/api/room/resume")
    await until(lambda: not app.state.store.preparing)
    state = (await client.get("/api/state")).json()
    assert state["context_checks"][0]["state"] == action
    assert state["paused"] == (action == "failed")
    current = state["leads"][0]
    for field in ("id", "name", "handle", "workspace", "provider", "model_id"):
        assert current[field] == lead[field]
    assert (current["conversation_id"] != lead["conversation_id"]) == (action == "reset")
    assert not backend.requests
