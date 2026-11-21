import httpx
import pytest

from department_studio.api import create_app
from department_studio.config import Settings
from tests.catalog import TEST_CATALOG
from tests.fakes import AutomaticBackend

OWNER = "project-owner"


@pytest.fixture
async def project_app(tmp_path):
    settings = Settings(
        pi_executable="/bin/true",
        data_dir=tmp_path / "data",
        stop_timeout_seconds=0.2,
    )
    app = create_app(
        settings,
        backend_factory=AutomaticBackend,
        catalog=TEST_CATALOG,
        owner_token=OWNER,
    )
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url=settings.origin,
            headers={"Authorization": f"Bearer {OWNER}"},
        ) as client:
            yield client, app, settings


async def test_first_project_is_listed_and_active(project_app):
    client, app, _ = project_app
    response = await client.get("/api/projects")
    assert response.status_code == 200
    data = response.json()
    assert data["active_id"] == data["projects"][0]["id"]
    assert data["projects"][0]["active"] is True
    assert data["projects"][0]["name"]


async def test_new_project_starts_empty_and_switch_restores_previous_room(project_app, tmp_path):
    client, app, _ = project_app
    first = (await client.get("/api/projects")).json()["active_id"]
    lead = (
        await client.post(
            "/api/leads",
            json={
                "name": "Alpha",
                "handle": "alpha",
                "role": "Build",
                "provider": "test",
                "model_id": "model-a",
                "workspace": str(tmp_path),
            },
        )
    ).json()
    created = (await client.post("/api/projects", json={"name": "Research"})).json()
    second = created["project"]
    assert created["active_id"] == second["id"]
    assert second["active"] is True
    assert (await client.get("/api/state")).json()["leads"] == []
    assert app.state.store.list_leads() == []
    switched = (await client.post(f"/api/projects/{first}/activate")).json()
    assert switched["active_id"] == first
    leads = (await client.get("/api/state")).json()["leads"]
    assert [item["id"] for item in leads] == [lead["id"]]


async def test_project_delete_requires_confirmation_and_active_is_protected(project_app):
    client, _, _ = project_app
    first = (await client.get("/api/projects")).json()["active_id"]
    second = (await client.post("/api/projects", json={"name": "Delete me"})).json()["project"]
    await client.post(f"/api/projects/{first}/activate")
    bad = await client.delete(f"/api/projects/{second['id']}", params={"confirm_name": "wrong"})
    assert bad.status_code == 422
    active = await client.delete(
        f"/api/projects/{first}", params={"confirm_name": "My first project"}
    )
    assert active.status_code == 409
    deleted = await client.delete(
        f"/api/projects/{second['id']}", params={"confirm_name": "Delete me"}
    )
    assert deleted.status_code == 200
    assert [item["id"] for item in deleted.json()["projects"]] == [first]


async def test_project_routes_require_the_owner_credential(project_app):
    client, _, _ = project_app
    response = await client.get("/api/projects", headers={"Authorization": ""})
    assert response.status_code == 401
    response = await client.get("/api/projects", headers={"Authorization": "Bearer wrong"})
    assert response.status_code == 401
