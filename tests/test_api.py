import json
from dataclasses import asdict

import httpx
import pytest

from department_studio.api import create_app
from department_studio.config import Settings
from department_studio.domain import LeadCreate
from tests.fakes import ControlledBackend, until

OWNER = "test-owner-credential"


@pytest.fixture
async def http_app(store, tmp_path):
    settings = Settings(pi_executable="/bin/true", data_dir=tmp_path, stop_timeout_seconds=0.1)
    backend = ControlledBackend()
    app = create_app(settings, store=store, backend=backend, owner_token=OWNER)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url=settings.origin,
            headers={"Authorization": f"Bearer {OWNER}"},
        ) as client:
            yield client, app, backend


def lead_body(tmp_path, **changes):
    return {
        "name": "星图 Studio",
        "handle": "atlas",
        "role": "Build a narrow API",
        "provider": "test",
        "model_id": "model-a",
        "workspace": str(tmp_path),
        "enabled": True,
        "permission": "discuss",
        **changes,
    }


async def test_first_run_empty_paused_and_user_configuration_persists(http_app, tmp_path):
    client, app, _ = http_app
    assert (await client.get("/api/state")).json() == {
        "paused": True,
        "leads": [],
        "messages": [],
        "deliveries": [],
    }
    created = await client.post("/api/leads", json=lead_body(tmp_path))
    assert created.status_code == 201
    lead = created.json()
    updated = await client.patch(
        f"/api/leads/{lead['id']}",
        json=lead_body(tmp_path, name="Foundry", handle="forge", revision=lead["revision"]),
    )
    assert updated.status_code == 200
    assert updated.json()["conversation_id"] == lead["conversation_id"]
    assert app.state.store.get_lead(lead["id"]).handle == "forge"
    models = (await client.get("/api/models", params={"workspace": str(tmp_path)})).json()
    assert models == {
        "models": [
            {"provider": "test", "id": "model-a", "name": "Synthetic A"},
            {"provider": "test", "id": "model-b", "name": "Synthetic B"},
        ]
    }


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("GET", "/api/state", None),
        ("GET", "/api/models", None),
        ("POST", "/api/leads", {}),
        ("PATCH", "/api/leads/missing", {}),
        ("POST", "/api/messages", {}),
        ("POST", "/api/room/resume", {}),
        ("POST", "/api/room/pause", {}),
        ("POST", "/api/bridge/messages", {}),
    ],
)
async def test_all_api_endpoints_require_header_credential(http_app, method, path, body):
    client, _, _ = http_app
    response = await client.request(method, path, json=body, headers={"Authorization": ""})
    assert response.status_code == 401
    response = await client.request(
        method, path + "?token=" + OWNER, json=body, headers={"Authorization": "Bearer invalid"}
    )
    assert response.status_code == 401


async def test_strict_host_origin_and_no_cors(http_app):
    client, _, _ = http_app
    for headers in (
        {"Origin": "https://evil.example"},
        {"Origin": "null"},
        {"Host": "evil.example"},
        {"Host": "localhost:8765"},
    ):
        response = await client.get("/api/state", headers=headers)
        assert response.status_code == 403
        assert "access-control-allow-origin" not in response.headers
    response = await client.get("/api/state", headers={"Origin": "http://127.0.0.1:8765"})
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]


async def test_runtime_scope_sender_immutability_idempotency_and_generation_revocation(
    http_app, tmp_path
):
    client, app, backend = http_app
    lead = (await client.post("/api/leads", json=lead_body(tmp_path))).json()
    await client.post("/api/room/resume")
    await client.post("/api/messages", json={"text": "@atlas work"})
    await until(lambda: backend.requests)
    token = backend.requests[0].bridge_token
    runtime = {"Authorization": "Bearer " + token}
    assert token != OWNER
    for path in ("/api/state", "/api/models"):
        assert (await client.get(path, headers=runtime)).status_code == 403
    for path in ("/api/leads", "/api/messages", "/api/room/pause", "/api/room/resume"):
        assert (await client.post(path, json={}, headers=runtime)).status_code == 403
    body = {"call_id": "tool-1", "text": "A public decision", "recipients": []}
    assert (await client.post("/api/bridge/messages", json=body)).status_code == 403
    spoof = await client.post(
        "/api/bridge/messages", json={**body, "sender_kind": "human"}, headers=runtime
    )
    assert spoof.status_code == 422
    first = await client.post("/api/bridge/messages", json=body, headers=runtime)
    assert first.status_code == 200
    repeated = await client.post("/api/bridge/messages", json=body, headers=runtime)
    assert repeated.json() == first.json()
    changed = await client.post(
        "/api/bridge/messages", json={**body, "text": "altered"}, headers=runtime
    )
    assert changed.status_code == 409
    message = app.state.store.get_message(first.json()["message_id"])
    assert message.sender_kind == "lead" and message.sender_id == lead["id"]
    await client.post("/api/room/pause")
    late = await client.post("/api/bridge/messages", json=body, headers=runtime)
    assert late.status_code == 409
    snapshot = json.dumps((await client.get("/api/state")).json())
    assert token not in snapshot and OWNER not in snapshot


async def test_validation_revision_busy_errors_and_safe_invalid_json(http_app, tmp_path):
    client, _, backend = http_app
    assert (
        await client.post("/api/leads", json=lead_body(tmp_path, enabled="yes"))
    ).status_code == 422
    assert (
        await client.post("/api/leads", json=lead_body(tmp_path, handle="all"))
    ).status_code == 422
    assert (await client.post("/api/messages", json={"text": "@unknown work"})).status_code == 422
    malformed = await client.post(
        "/api/messages", content='{"secret-value', headers={"Content-Type": "application/json"}
    )
    assert malformed.status_code == 422 and "secret-value" not in malformed.text
    lead = (await client.post("/api/leads", json=lead_body(tmp_path))).json()
    assert (
        await client.patch(f"/api/leads/{lead['id']}", json=lead_body(tmp_path, revision=999))
    ).status_code == 409
    await client.post("/api/room/resume")
    await client.post("/api/messages", json={"text": "@atlas work"})
    await until(lambda: backend.requests)
    assert (
        await client.patch(
            f"/api/leads/{lead['id']}", json=lead_body(tmp_path, revision=lead["revision"])
        )
    ).status_code == 409


async def test_model_failure_is_sanitized_and_disappeared_workspace_is_invalid(http_app, tmp_path):
    client, _, backend = http_app

    async def broken(workspace):
        raise RuntimeError("provider header secret-value")

    backend.list_models = broken
    result = await client.get("/api/models", params={"workspace": str(tmp_path)})
    assert result.status_code == 503 and "secret-value" not in result.text
    result = await client.get("/api/models", params={"workspace": str(tmp_path / "missing")})
    assert result.status_code == 422


async def test_new_owner_token_and_paused_recovery_after_application_restart(tmp_path):
    settings = Settings(pi_executable="/bin/true", data_dir=tmp_path / "data")
    first = create_app(settings, backend=ControlledBackend())
    async with first.router.lifespan_context(first):
        lead = first.state.store.create_lead(LeadCreate(**lead_body(tmp_path)))
        first.state.service.resume()
        first.state.store.post_public_reply(lead.id, "Prior name is durable")
    second = create_app(settings, backend=ControlledBackend())
    async with second.router.lifespan_context(second):
        assert second.state.owner.token != first.state.owner.token
        assert second.state.store.paused
        assert asdict(second.state.store.list_leads()[0])["id"] == lead.id
        assert second.state.store.list_messages()[0].sender_name == "星图 Studio"
