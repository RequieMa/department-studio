"""Project rooms: a small metadata catalog and one isolated Store/Service per project.

Every project owns its room.sqlite and native session directory. Switching closes the
previous room service before opening the next one; deleting a project removes only
Studio's private data, never the configured workspace.
"""

import asyncio
import json
import os
import re
import shutil
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from department_studio.backends.base import AgentBackend
from department_studio.backends.claude import ClaudeBackend
from department_studio.backends.deepseek import DeepSeekBackend
from department_studio.backends.pi import PiBackend
from department_studio.backends.registry import RuntimeRegistry
from department_studio.config import Settings
from department_studio.domain import Conflict, Invalid, NotFound
from department_studio.models import ModelCatalog
from department_studio.records import RecordStore
from department_studio.service import RoomService
from department_studio.store import Store

_PROJECT_ID = re.compile(r"[a-zA-Z0-9_-]{1,64}")
_PROJECT_NAME_MAX = 80


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _name(value) -> str:
    if not isinstance(value, str):
        raise Invalid("Project name must be text.")
    name = " ".join(value.split())
    if not name or len(name) > _PROJECT_NAME_MAX:
        raise Invalid(f"Project name must contain 1–{_PROJECT_NAME_MAX} characters.")
    if any(ord(character) < 32 for character in name) or any(
        separator in name for separator in ("/", "\\", "\0")
    ):
        raise Invalid("Project name contains unsupported characters.")
    return name


def _write_json(path: Path, payload: dict):
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    temporary.chmod(0o600)
    os.replace(temporary, path)


def _read_json(path: Path) -> dict | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return None
    return value if isinstance(value, dict) else None


@dataclass(frozen=True)
class Project:
    id: str
    name: str
    path: Path
    created_at: str
    last_opened_at: str
    legacy: bool = False
    active: bool = False

    def info(self) -> "ProjectInfo":
        return ProjectInfo(
            id=self.id,
            name=self.name,
            created_at=self.created_at,
            last_opened_at=self.last_opened_at,
            active=self.active,
        )


@dataclass(frozen=True)
class ProjectInfo:
    id: str
    name: str
    created_at: str
    last_opened_at: str
    active: bool


class ProjectCatalog:
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir).expanduser().resolve()
        self.projects_dir = self.data_dir / "projects"
        self.active_file = self.data_dir / "active_project.json"
        self.legacy_meta = self.data_dir / "project.json"

    def ensure_initial(self) -> Project:
        projects = self.list()
        if projects:
            active = self.active_id()
            selected = next((item for item in projects if item.id == active), None)
            if selected is None:
                selected = max(projects, key=lambda item: (item.last_opened_at, item.created_at))
                self.set_active(selected.id)
            return selected
        if (self.data_dir / "room.sqlite").exists() or self.legacy_meta.exists():
            project = self._ensure_legacy()
            if self.active_id() != project.id:
                self.set_active(project.id)
            return self.get(project.id)
        project = self.create("My first project")
        self.set_active(project.id)
        return self.get(project.id)

    def _ensure_legacy(self) -> Project:
        now = _now()
        raw = _read_json(self.legacy_meta)
        if raw is None:
            try:
                created = datetime.fromtimestamp(
                    (self.data_dir / "room.sqlite").stat().st_mtime, UTC
                ).isoformat()
            except OSError:
                created = now
            raw = {
                "id": uuid4().hex,
                "name": "My first project",
                "created_at": created,
                "last_opened_at": now,
            }
            self.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            self.data_dir.chmod(0o700)
            _write_json(self.legacy_meta, raw)
        project = self._project(raw, self.data_dir, legacy=True)
        if project is None:
            raise RuntimeError("The legacy project metadata is invalid.")
        return project

    def _project(self, raw: dict, path: Path, *, legacy: bool) -> Project | None:
        project_id = raw.get("id")
        name = raw.get("name")
        created = raw.get("created_at")
        opened = raw.get("last_opened_at")
        if (
            not isinstance(project_id, str)
            or not _PROJECT_ID.fullmatch(project_id)
            or not isinstance(name, str)
            or not name.strip()
            or len(name) > _PROJECT_NAME_MAX
            or not isinstance(created, str)
            or not isinstance(opened, str)
        ):
            return None
        return Project(
            id=project_id,
            name=name,
            path=path,
            created_at=created,
            last_opened_at=opened,
            legacy=legacy,
            active=project_id == self.active_id(),
        )

    def list(self) -> list[Project]:
        active = self.active_id()
        projects: list[Project] = []
        if self.legacy_meta.is_file():
            project = self._project(_read_json(self.legacy_meta) or {}, self.data_dir, legacy=True)
            if project is not None:
                projects.append(project)
        if self.projects_dir.is_dir():
            try:
                children = sorted(self.projects_dir.iterdir())
            except OSError:
                children = []
            for path in children:
                try:
                    if path.is_symlink() or not path.is_dir():
                        continue
                    resolved = path.resolve()
                    if resolved.parent != self.projects_dir.resolve():
                        continue
                    raw = _read_json(path / "project.json")
                    project = self._project(raw or {}, path, legacy=False)
                except OSError:
                    continue
                if project is not None and project.id == path.name:
                    projects.append(project)
        for project in projects:
            object.__setattr__(project, "active", project.id == active)
        return sorted(projects, key=lambda item: (item.created_at, item.name.casefold()))

    def active_id(self) -> str | None:
        raw = _read_json(self.active_file)
        value = raw.get("project_id") if raw else None
        return value if isinstance(value, str) and _PROJECT_ID.fullmatch(value) else None

    def set_active(self, project_id: str):
        self.get(project_id)
        self.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        _write_json(self.active_file, {"project_id": project_id})

    def get(self, project_id: str) -> Project:
        if not isinstance(project_id, str) or not _PROJECT_ID.fullmatch(project_id):
            raise NotFound("Project not found.")
        for project in self.list():
            if project.id == project_id:
                return project
        raise NotFound("Project not found.")

    def create(self, name: str) -> Project:
        name = _name(name)
        if any(item.name.casefold() == name.casefold() for item in self.list()):
            raise Conflict("A project with that name already exists.")
        project_id = uuid4().hex
        path = self.projects_dir / project_id
        self.projects_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.mkdir(mode=0o700)
        path.chmod(0o700)
        now = _now()
        project = Project(
            id=project_id,
            name=name,
            path=path,
            created_at=now,
            last_opened_at=now,
            legacy=False,
            active=False,
        )
        _write_json(
            path / "project.json",
            {
                "id": project.id,
                "name": project.name,
                "created_at": project.created_at,
                "last_opened_at": project.last_opened_at,
            },
        )
        return project

    def touch(self, project_id: str) -> Project:
        project = self.get(project_id)
        updated = Project(
            id=project.id,
            name=project.name,
            path=project.path,
            created_at=project.created_at,
            last_opened_at=_now(),
            legacy=project.legacy,
            active=True,
        )
        meta_path = self.legacy_meta if project.legacy else project.path / "project.json"
        _write_json(
            meta_path,
            {
                "id": updated.id,
                "name": updated.name,
                "created_at": updated.created_at,
                "last_opened_at": updated.last_opened_at,
            },
        )
        return updated

    def delete(self, project_id: str):
        project = self.get(project_id)
        if project.active:
            raise Conflict("Switch away from the active project before deleting it.")
        if len(self.list()) <= 1:
            raise Conflict("The only project cannot be deleted.")
        if project.legacy:
            for name in ("room.sqlite", "room.sqlite-wal", "room.sqlite-shm"):
                try:
                    (self.data_dir / name).unlink()
                except FileNotFoundError:
                    pass
            if (self.data_dir / "sessions").is_dir():
                shutil.rmtree(self.data_dir / "sessions")
            if (self.data_dir / "records").is_dir():
                shutil.rmtree(self.data_dir / "records")
            try:
                self.legacy_meta.unlink()
            except FileNotFoundError:
                pass
        else:
            resolved = project.path.resolve()
            if resolved.parent != self.projects_dir.resolve():
                raise Conflict("Refusing to delete a path outside the project directory.")
            shutil.rmtree(resolved)
        if self.active_id() == project_id:
            try:
                self.active_file.unlink()
            except FileNotFoundError:
                pass


@dataclass
class ActiveProject:
    project: Project
    store: Store
    service: RoomService
    records: RecordStore


class ProjectManager:
    """Open one project at a time; switching confirms the previous stop first."""

    def __init__(
        self,
        settings: Settings,
        models: ModelCatalog,
        *,
        backend_factory: Callable[[], AgentBackend] | None = None,
        project_catalog: ProjectCatalog | None = None,
    ):
        self.settings = settings
        self.models = models
        self.catalog = project_catalog or ProjectCatalog(settings.data_dir)
        self._backend_factory = backend_factory
        self._active: ActiveProject | None = None
        self._lock = asyncio.Lock()
        self._closed = False
        self.busy = False

    @property
    def active(self) -> ActiveProject:
        if self._active is None:
            raise RuntimeError("No project is active.")
        return self._active

    @property
    def store(self) -> Store:
        return self.active.store

    @property
    def service(self) -> RoomService:
        return self.active.service

    @property
    def records(self) -> RecordStore:
        return self.active.records

    @property
    def project(self) -> ProjectInfo:
        return self.catalog.get(self.active.project.id).info()

    def projects(self) -> list[ProjectInfo]:
        return [item.info() for item in self.catalog.list()]

    def info(self, project_id: str) -> ProjectInfo:
        return self.catalog.get(project_id).info()

    def _registry(self, settings: Settings) -> RuntimeRegistry:
        if self._backend_factory is not None:
            return RuntimeRegistry.single(self._backend_factory())
        return RuntimeRegistry(
            {
                "pi": PiBackend(settings, self.models),
                "claude": ClaudeBackend(settings, self.models),
                "deepseek": DeepSeekBackend(settings, self.models),
            }
        )

    async def _open(self, project: Project) -> ActiveProject:
        project.path.mkdir(parents=True, exist_ok=True, mode=0o700)
        project.path.chmod(0o700)
        sessions = project.path / "sessions"
        sessions.mkdir(exist_ok=True, mode=0o700)
        sessions.chmod(0o700)
        project_settings = replace(self.settings, data_dir=project.path)
        store = Store(
            project.path / "room.sqlite",
            max_chain_deliveries=self.settings.max_chain_deliveries,
        )
        records = RecordStore(project.path / "records").ensure()
        registry = self._registry(project_settings)
        service = RoomService(store, registry, project_settings, self.models, records)
        try:
            await service.start()
        except BaseException:
            store.close()
            try:
                await registry.close()
            except Exception:
                pass
            raise
        return ActiveProject(project, store, service, records)

    def _mark_active(self, active: ActiveProject):
        self._active = active
        self.catalog.set_active(active.project.id)
        self.catalog.touch(active.project.id)
        self._active.project = self.catalog.get(active.project.id)

    async def start(self):
        if self._active is not None:
            raise RuntimeError("Project manager already started.")
        project = self.catalog.ensure_initial()
        active = await self._open(project)
        self._mark_active(active)

    async def _switch_locked(self, project_id: str) -> ProjectInfo:
        if self._active is not None and self._active.project.id == project_id:
            return self.active.project.info()
        project = self.catalog.get(project_id)
        previous = self._active
        if previous is not None:
            await previous.service.close()
            if not previous.service.shutdown_confirmed:
                raise Conflict(
                    "The current project could not confirm runtime stop; inspect local "
                    "processes before switching."
                )
            previous.store.close()
            self._active = None
        try:
            active = await self._open(project)
        except BaseException:
            if previous is not None:
                try:
                    reopened = await self._open(previous.project)
                    self._active = reopened
                except Exception:
                    self._active = None
            raise
        self._mark_active(active)
        return self.catalog.get(active.project.id).info()

    async def switch(self, project_id: str) -> ProjectInfo:
        async with self._lock:
            if self._closed:
                raise RuntimeError("Project manager is closed.")
            self.busy = True
            try:
                return await self._switch_locked(project_id)
            finally:
                self.busy = False

    async def create(self, name: str) -> ProjectInfo:
        async with self._lock:
            if self._closed:
                raise RuntimeError("Project manager is closed.")
            project = self.catalog.create(name)
            self.busy = True
            try:
                return await self._switch_locked(project.id)
            finally:
                self.busy = False

    async def delete(self, project_id: str):
        async with self._lock:
            if self._closed:
                raise RuntimeError("Project manager is closed.")
            if self._active is not None and self._active.project.id == project_id:
                raise Conflict("Switch away from the active project before deleting it.")
            self.catalog.delete(project_id)

    async def close(self):
        async with self._lock:
            if self._closed:
                return
            self._closed = True
            if self._active is not None:
                await self._active.service.close()
                self._active.store.close()
                self._active = None


class EmbeddedProjectManager:
    """Single-project lifecycle for tests and embedders that supply a Store."""

    def __init__(
        self,
        settings: Settings,
        store: Store,
        service: RoomService,
        records: RecordStore,
    ):
        now = _now()
        self._project = ProjectInfo(
            id="embedded",
            name="Current project",
            created_at=now,
            last_opened_at=now,
            active=True,
        )
        self._store = store
        self._service = service
        self.records = records
        self.busy = False

    @property
    def store(self) -> Store:
        return self._store

    @property
    def service(self) -> RoomService:
        return self._service

    @property
    def project(self) -> ProjectInfo:
        return self._project

    def projects(self) -> list[ProjectInfo]:
        return [self._project]

    def info(self, project_id: str) -> ProjectInfo:
        if project_id != self._project.id:
            raise NotFound("Project not found.")
        return self._project

    async def switch(self, project_id: str) -> ProjectInfo:
        raise Conflict("Project switching is unavailable in this embedded session.")

    async def create(self, name: str) -> ProjectInfo:
        raise Conflict("Project creation is unavailable in this embedded session.")

    async def delete(self, project_id: str):
        raise Conflict("Project deletion is unavailable in this embedded session.")

    async def close(self):
        await self._service.close()
