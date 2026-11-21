import pytest

from department_studio.config import Settings
from department_studio.domain import Conflict, Invalid, LeadCreate, NotFound
from department_studio.projects import ProjectCatalog, ProjectManager
from department_studio.store import Store
from tests.catalog import TEST_CATALOG
from tests.fakes import AutomaticBackend


def catalog(tmp_path):
    return ProjectCatalog(tmp_path / "data")


def test_initial_project_is_created_and_active(tmp_path):
    projects = catalog(tmp_path)
    project = projects.ensure_initial()
    assert project.name
    assert project.path.is_dir()
    assert project.path.parent.name == "projects"
    assert projects.active_id() == project.id
    listed = projects.list()
    assert [(item.id, item.active) for item in listed] == [(project.id, True)]


def test_existing_root_room_becomes_a_legacy_project_without_moving_it(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    with Store(data / "room.sqlite") as store:
        store.post_human_message("Existing room history")
    (data / "sessions").mkdir()
    projects = ProjectCatalog(data)
    project = projects.ensure_initial()
    assert project.legacy is True
    assert project.path == data
    assert (data / "room.sqlite").is_file()
    assert (data / "project.json").is_file()
    assert projects.list()[0].id == project.id


def test_new_projects_have_isolated_directories_and_unique_names(tmp_path):
    projects = catalog(tmp_path)
    first = projects.ensure_initial()
    second = projects.create("  Research room  ")
    assert second.name == "Research room"
    assert second.path != first.path
    assert second.path.parent == projects.projects_dir
    with pytest.raises(Conflict, match="already exists"):
        projects.create("research ROOM")
    with pytest.raises(Invalid):
        projects.create("   ")
    with pytest.raises(Invalid):
        projects.create("bad/name")
    assert len(projects.list()) == 2


def test_active_project_is_persisted_and_invalid_ids_are_not_found(tmp_path):
    projects = catalog(tmp_path)
    first = projects.ensure_initial()
    second = projects.create("Second")
    projects.set_active(second.id)
    reopened = ProjectCatalog(tmp_path / "data")
    assert reopened.active_id() == second.id
    assert reopened.get(second.id).name == "Second"
    with pytest.raises(NotFound):
        reopened.get("../../escape")
    with pytest.raises(NotFound):
        reopened.get(first.id + "x")


def test_deletion_removes_only_the_inactive_project_data(tmp_path):
    projects = catalog(tmp_path)
    first = projects.ensure_initial()
    second = projects.create("Second")
    projects.set_active(first.id)
    with pytest.raises(Conflict, match="active"):
        projects.delete(first.id)
    projects.delete(second.id)
    assert not second.path.exists()
    assert [item.id for item in projects.list()] == [first.id]
    with pytest.raises(Conflict, match="active"):
        projects.delete(first.id)


def test_legacy_project_deletion_keeps_the_data_root(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    with Store(data / "room.sqlite") as store:
        store.post_human_message("keep me until deletion")
    (data / "sessions").mkdir()
    projects = ProjectCatalog(data)
    legacy = projects.ensure_initial()
    other = projects.create("Other")
    projects.set_active(other.id)
    projects.delete(legacy.id)
    assert data.is_dir()
    assert not (data / "room.sqlite").exists()
    assert not (data / "sessions").exists()
    assert not (data / "project.json").exists()
    assert [item.id for item in projects.list()] == [other.id]


async def test_manager_switches_between_isolated_rooms_and_restores_active(store, tmp_path):
    settings = Settings(pi_executable="/bin/true", data_dir=tmp_path / "data")
    closed = []

    def factory():
        backend = AutomaticBackend()
        original = backend.close

        async def close():
            closed.append(backend)
            await original()

        backend.close = close
        return backend

    manager = ProjectManager(settings, TEST_CATALOG, backend_factory=factory)
    await manager.start()
    first = manager.project
    assert manager.records.root == manager.active.project.path / "records"
    assert (manager.records.root / "README.md").is_file()
    manager.records.write("2026-11-21-first.md", "first project note", "create")
    manager.store.create_lead(
        LeadCreate("Alpha", "alpha", "Build", "test", "model-a", str(tmp_path))
    )
    second = await manager.create("Second")
    assert manager.project.id == second.id
    assert manager.store.list_leads() == []
    assert not manager.records.list() or all(
        item["name"] != "2026-11-21-first.md" for item in manager.records.list()
    )
    manager.records.write("2026-11-21-second.md", "second project note", "create")
    assert closed
    await manager.switch(first.id)
    assert [lead.handle for lead in manager.store.list_leads()] == ["alpha"]
    assert any(item["name"] == "2026-11-21-first.md" for item in manager.records.list())
    await manager.close()

    reopened = ProjectManager(settings, TEST_CATALOG, backend_factory=factory)
    await reopened.start()
    assert reopened.project.id == first.id
    assert [lead.handle for lead in reopened.store.list_leads()] == ["alpha"]
    await reopened.delete(second.id)
    assert not (settings.data_dir / "projects" / second.id).exists()
    with pytest.raises(Conflict, match="active"):
        await reopened.delete(first.id)
    await reopened.close()


async def test_manager_legacy_room_is_opened_through_the_same_lifecycle(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    with Store(data / "room.sqlite") as store:
        store.post_human_message("Legacy message")
    manager = ProjectManager(
        Settings(pi_executable="/bin/true", data_dir=data),
        TEST_CATALOG,
        backend_factory=AutomaticBackend,
    )
    await manager.start()
    assert manager.active.project.legacy is True
    assert manager.store.list_messages()[0].text == "Legacy message"
    await manager.close()


async def test_switch_and_create_are_serialized_and_report_busy(store, tmp_path):
    settings = Settings(
        pi_executable="/bin/true", data_dir=tmp_path / "data", stop_timeout_seconds=0.1
    )
    manager = ProjectManager(settings, TEST_CATALOG, backend_factory=AutomaticBackend)
    await manager.start()
    first = manager.project
    second = await manager.create("Second")
    assert manager.project.id == second.id
    assert manager.busy is False
    await manager.switch(first.id)
    assert manager.busy is False
    await manager.close()
