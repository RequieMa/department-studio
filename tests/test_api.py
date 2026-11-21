import json
import os
from dataclasses import asdict
from pathlib import Path

import httpx
import pytest

from department_studio.api import create_app
from department_studio.config import Settings
from department_studio.domain import LeadCreate
from tests.catalog import TEST_CATALOG
from tests.fakes import ControlledBackend, until

OWNER = "test-owner-credential"


@pytest.fixture
async def http_app(store, tmp_path):
    settings = Settings(pi_executable="/bin/true", data_dir=tmp_path, stop_timeout_seconds=0.1)
    backend = ControlledBackend()
    app = create_app(
        settings, store=store, backend=backend, catalog=TEST_CATALOG, owner_token=OWNER
    )
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
        "preparing": False,
        "context_checks": [],
        "active_recipient_ids": [],
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
    assert [item["id"] for item in models["models"]] == [
        "model-a",
        "model-b",
        "model-c",
        "model-d",
        "fixture",
    ]
    assert models["models"][0] == {
        "provider": "test",
        "id": "model-a",
        "name": "Synthetic A",
        "provider_name": "Synthetic",
        "context_window": 128000,
        "runtimes": ["pi", "claude", "deepseek"],
        "credential_env": None,
        "credential_ready": True,
    }
    assert {item["kind"] for item in models["runtimes"]} == {"pi", "claude", "deepseek"}


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("GET", "/api/state", None),
        ("GET", "/api/models", None),
        ("GET", "/api/runtimes", None),
        ("GET", "/api/folders", None),
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
    await until(lambda: not app.state.store.paused)
    await client.post("/api/messages", json={"text": "@atlas work"})
    await until(lambda: backend.requests)
    token = backend.requests[0].bridge_token
    runtime = {"Authorization": "Bearer " + token}
    assert token != OWNER
    for path in ("/api/state", "/api/models", "/api/folders"):
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
    client, app, backend = http_app
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
    await until(lambda: not app.state.store.paused)
    await client.post("/api/messages", json={"text": "@atlas work"})
    await until(lambda: backend.requests)
    assert (
        await client.patch(
            f"/api/leads/{lead['id']}", json=lead_body(tmp_path, revision=lead["revision"])
        )
    ).status_code == 409


async def test_models_come_from_the_catalog_and_unknown_runtimes_are_rejected(http_app, tmp_path):
    client, _, backend = http_app
    result = await client.get("/api/models", params={"workspace": str(tmp_path)})
    assert result.status_code == 200
    assert "secret-value" not in result.text
    assert {model["id"] for model in result.json()["models"]} >= {"model-a", "model-b"}
    unknown = await client.get("/api/models", params={"runtime": "unknown"})
    assert unknown.status_code == 422 and "Unknown agent runtime" in unknown.text
    runtimes = await client.get("/api/runtimes")
    assert runtimes.status_code == 200
    assert {item["kind"] for item in runtimes.json()["runtimes"]} == {
        "pi",
        "claude",
        "deepseek",
    }
    # Listing never starts a runtime or asks a runtime for its own catalog.
    assert not backend.requests
    assert not getattr(backend, "closed", False)


async def test_folder_browser_lists_only_directories_without_starting_a_runtime(
    http_app, tmp_path, monkeypatch
):
    client, _, backend = http_app
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    for name in ("星图 folder", "Zoo", "alpha", ".worktrees"):
        (workspace / name).mkdir()
    (workspace / "private.txt").write_text("private-file-contents")
    (workspace / "alias").symlink_to(workspace / "alpha", target_is_directory=True)
    (workspace / "broken").symlink_to(workspace / "missing", target_is_directory=True)
    monkeypatch.chdir(workspace)

    response = await client.get("/api/folders")

    assert response.status_code == 200
    assert response.json() == {
        "path": str(workspace),
        "parent": str(tmp_path),
        "folders": [
            {"name": ".worktrees", "path": str(workspace / ".worktrees")},
            {"name": "alias", "path": str(workspace / "alpha")},
            {"name": "alpha", "path": str(workspace / "alpha")},
            {"name": "Zoo", "path": str(workspace / "Zoo")},
            {"name": "星图 folder", "path": str(workspace / "星图 folder")},
        ],
    }
    assert "private" not in response.text
    assert backend.requests == []


async def test_folder_browser_can_select_empty_folders_and_navigate_to_root(http_app, tmp_path):
    client, _, _ = http_app
    empty = tmp_path / "empty folder"
    empty.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(empty, target_is_directory=True)

    response = await client.get("/api/folders", params={"path": str(alias)})
    assert response.status_code == 200
    assert response.json() == {"path": str(empty), "parent": str(tmp_path), "folders": []}

    root = await client.get("/api/folders", params={"path": str(tmp_path.anchor)})
    assert root.status_code == 200
    assert root.json()["parent"] is None


@pytest.mark.parametrize("value", ["missing", "file", "", "\x00", "x" * 4097])
async def test_folder_browser_rejects_invalid_paths(http_app, tmp_path, value):
    client, _, _ = http_app
    (tmp_path / "file").write_text("private-file-contents")
    path = str(tmp_path / value) if value in {"missing", "file"} else value
    response = await client.get("/api/folders", params={"path": path})
    assert response.status_code == 422
    assert "private-file-contents" not in response.text


async def test_folder_browser_reports_inaccessible_directory_without_raw_errors(
    http_app, tmp_path, monkeypatch
):
    client, _, _ = http_app
    restricted = tmp_path / "restricted"
    restricted.mkdir()
    scandir = os.scandir

    def denied(path):
        if Path(path) == restricted:
            raise PermissionError("private-native-error")
        return scandir(path)

    monkeypatch.setattr(os, "scandir", denied)
    response = await client.get("/api/folders", params={"path": str(restricted)})
    assert response.status_code == 422
    assert "access" in response.json()["detail"].lower()
    assert "private-native-error" not in response.text


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


async def test_unconfigured_legacy_model_fails_before_the_runtime_is_started(http_app, tmp_path):
    client, app, backend = http_app
    body = lead_body(tmp_path, provider="legacy-provider", model_id="legacy-model")
    assert (await client.post("/api/leads", json=body)).status_code == 201
    assert (await client.post("/api/room/resume")).status_code == 200
    await until(lambda: not app.state.store.paused)
    receipt = (await client.post("/api/messages", json={"text": "@atlas continue"})).json()
    assert receipt["recipient_ids"]
    await until(
        lambda: any(delivery.state == "failed" for delivery in app.state.store.list_deliveries())
    )
    failed = app.state.store.list_deliveries()[0]
    assert "not configured" in (failed.error or "")
    assert not backend.requests


async def test_department_runtime_selection_persists_and_rejects_unknown_values(http_app, tmp_path):
    client, app, _ = http_app
    response = await client.post(
        "/api/leads", json=lead_body(tmp_path, backend_kind="claude", handle="claude-lead")
    )
    assert response.status_code == 201
    assert response.json()["backend_kind"] == "claude"
    assert app.state.store.get_lead(response.json()["id"]).backend_kind == "claude"
    invalid = await client.post(
        "/api/leads", json=lead_body(tmp_path, backend_kind="other", handle="other-lead")
    )
    assert invalid.status_code == 422
    assert "other" not in invalid.text


async def test_runtime_availability_is_reported_without_starting_a_process(store, tmp_path):
    from department_studio.config import Settings

    settings = Settings(
        pi_executable="/missing/pi",
        claude_executable="/missing/claude",
        deepseek_executable="/missing/dsh",
        data_dir=tmp_path,
        stop_timeout_seconds=0.1,
    )
    app = create_app(settings, store=store, catalog=TEST_CATALOG, owner_token=OWNER)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url=settings.origin,
            headers={"Authorization": f"Bearer {OWNER}"},
        ) as client:
            response = await client.get("/api/runtimes")
            assert response.status_code == 200
            infos = {item["kind"]: item for item in response.json()["runtimes"]}
            assert all(item["available"] is False for item in infos.values())
            assert infos["claude"]["capabilities"]["room_bridge"] is True


async def test_api_continuation_and_public_note_addressing(http_app, tmp_path):
    client, app, _ = http_app
    lead = (await client.post("/api/leads", json=lead_body(tmp_path))).json()
    await client.post("/api/room/resume")
    await until(lambda: not app.state.store.paused)
    await client.post("/api/messages", json={"text": "@atlas first"})
    await client.post("/api/messages", json={"text": "follow up"})
    humans = [
        message
        for message in (await client.get("/api/state")).json()["messages"]
        if message["sender_kind"] == "human"
    ]
    assert humans[-1]["recipient_ids"] == [lead["id"]]
    assert (await client.get("/api/state")).json()["active_recipient_ids"] == [lead["id"]]
    note = await client.post("/api/messages", json={"text": "public note", "public_note": True})
    assert note.status_code == 200
    humans = [
        message
        for message in (await client.get("/api/state")).json()["messages"]
        if message["sender_kind"] == "human"
    ]
    assert humans[-1]["recipient_ids"] == []
    assert (await client.get("/api/state")).json()["active_recipient_ids"] == [lead["id"]]
    invalid = await client.post("/api/messages", json={"text": "note", "public_note": "yes"})
    assert invalid.status_code == 422
