"""Authenticated local HTTP boundary for the runtime-neutral room service."""

from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from department_studio.backends.base import AgentBackend
from department_studio.backends.claude import ClaudeBackend
from department_studio.backends.deepseek import DeepSeekBackend
from department_studio.backends.pi import PiBackend
from department_studio.backends.registry import RuntimeRegistry
from department_studio.config import DataDirectory, Settings
from department_studio.domain import Conflict, Invalid, LeadCreate, NotFound
from department_studio.folders import browse_folders
from department_studio.hierarchy_api import router as hierarchy_router
from department_studio.models import ModelCatalog, ModelCatalogError, load_catalog
from department_studio.project_api import router as project_router
from department_studio.projects import EmbeddedProjectManager, ProjectManager
from department_studio.records import RecordStore
from department_studio.records_api import router as records_router
from department_studio.security import OwnerCredential, allowed_request
from department_studio.service import RoomService
from department_studio.store import Store
from department_studio.task_api import router as task_router
from department_studio.tasks import TaskConflict

SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; "
    "connect-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'; "
    "frame-ancestors 'none'; form-action 'self'",
}


class StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class LeadBody(StrictBody):
    name: str = Field(max_length=80)
    handle: str = Field(max_length=32)
    role: str = Field(max_length=8000)
    provider: str = Field(max_length=200)
    model_id: str = Field(max_length=200)
    worker_provider: str = Field(default="", max_length=200)
    worker_model_id: str = Field(default="", max_length=200)
    workspace: str = Field(max_length=4096)
    enabled: bool = True
    backend_kind: Literal["pi", "claude", "deepseek"] = "pi"


class LeadPatch(LeadBody):
    enabled: bool
    revision: int = Field(ge=1)


class MessageBody(StrictBody):
    text: str = Field(min_length=1, max_length=32000)
    public_note: bool = False


class BridgeBody(MessageBody):
    call_id: str = Field(min_length=1, max_length=200)
    recipients: list[str] = Field(default_factory=list, max_length=64)


class BridgeRecordBody(StrictBody):
    name: str = Field(min_length=1, max_length=128)
    content: str = Field(min_length=1, max_length=524288)
    mode: Literal["append", "replace"] = "append"


def _registry(
    settings: Settings,
    models: ModelCatalog,
    backend: AgentBackend | None,
    backend_factory: Callable[[], AgentBackend] | None,
) -> RuntimeRegistry:
    if backend_factory is not None:
        return RuntimeRegistry.single(backend_factory())
    if backend is not None:
        return RuntimeRegistry.single(backend)
    return RuntimeRegistry(
        {
            "pi": PiBackend(settings, models),
            "claude": ClaudeBackend(settings, models),
            "deepseek": DeepSeekBackend(settings, models),
        }
    )


def create_app(
    settings: Settings,
    *,
    store: Store | None = None,
    backend: AgentBackend | None = None,
    backend_factory: Callable[[], AgentBackend] | None = None,
    catalog: ModelCatalog | None = None,
    owner_token: str | None = None,
) -> FastAPI:
    owner = OwnerCredential(owner_token) if owner_token else OwnerCredential()
    models = catalog or load_catalog(settings.models_config)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if store is not None:
            registry = _registry(settings, models, backend, backend_factory)
            records = RecordStore(settings.data_dir / "records").ensure()
            service = RoomService(store, registry, settings, models, records)
            manager = EmbeddedProjectManager(settings, store, service, records)
            app.state.projects = manager
            app.state.store = store
            app.state.service = service
            app.state.records = records
            app.state.catalog = models
            await service.start()
            try:
                yield
            finally:
                await manager.close()
                if not service.shutdown_confirmed:
                    raise RuntimeError(
                        "Shutdown could not confirm runtime stop. Inspect local processes."
                    )
            return
        with DataDirectory(settings.data_dir):
            factory = backend_factory or ((lambda: backend) if backend is not None else None)
            manager = ProjectManager(settings, models, backend_factory=factory)
            await manager.start()
            app.state.projects = manager
            app.state.store = manager.store
            app.state.service = manager.service
            app.state.records = manager.records
            app.state.catalog = models
            try:
                yield
            finally:
                await manager.close()
                if not app.state.service.shutdown_confirmed:
                    raise RuntimeError(
                        "Shutdown could not confirm runtime stop. Inspect local processes."
                    )

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.owner = owner
    app.include_router(task_router)
    app.include_router(project_router)
    app.include_router(hierarchy_router)
    app.include_router(records_router)

    @app.middleware("http")
    async def local_access(request: Request, call_next):
        def reject(status, detail):
            return JSONResponse({"detail": detail}, status_code=status, headers=SECURITY_HEADERS)

        if (
            len(request.headers.getlist("host")) != 1
            or len(request.headers.getlist("origin")) > 1
            or not allowed_request(
                settings.origin, request.headers.get("host"), request.headers.get("origin")
            )
        ):
            return reject(403, "Unexpected service host or browser origin.")
        if request.url.path.startswith("/api/"):
            authorization = request.headers.get("authorization", "")
            scheme, _, token = authorization.partition(" ")
            if (
                len(request.headers.getlist("authorization")) != 1
                or scheme.lower() != "bearer"
                or not token
                or len(token) > 512
            ):
                return reject(401, "A valid launch or runtime credential is required.")
            is_owner = owner.matches(token)
            is_runtime = app.state.service.knows_bridge_token(token)
            if not is_owner and not is_runtime:
                return reject(401, "A valid launch or runtime credential is required.")
            bridge = request.url.path.startswith("/api/bridge/")
            if (bridge and not is_runtime) or (not bridge and not is_owner):
                return reject(403, "This credential cannot perform that action.")
            request.state.token = token
        projects = getattr(app.state, "projects", None)
        if (
            projects is not None
            and getattr(projects, "busy", False)
            and request.url.path.startswith("/api/")
            and not request.url.path.startswith("/api/projects")
        ):
            return reject(503, "A project switch is in progress; retry shortly.")
        response = await call_next(request)
        response.headers.update(SECURITY_HEADERS)
        return response

    @app.exception_handler(Invalid)
    async def invalid_handler(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.exception_handler(Conflict)
    async def conflict_handler(request, exc):
        content = {"detail": str(exc)}
        if isinstance(exc, TaskConflict):
            content["code"] = exc.code
        return JSONResponse(content, status_code=409)

    @app.exception_handler(NotFound)
    async def missing_handler(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=404)

    @app.exception_handler(ModelCatalogError)
    async def model_catalog_handler(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request, exc):
        # Pydantic's default response includes rejected inputs; omit them.
        return JSONResponse(
            {
                "detail": "Invalid request data.",
                "errors": [
                    {"field": ".".join(map(str, error["loc"])), "type": error["type"]}
                    for error in exc.errors()
                ],
            },
            status_code=422,
        )

    @app.get("/api/state")
    async def state():
        return app.state.store.snapshot()

    @app.get("/api/folders")
    def folders(path: str | None = Query(default=None, max_length=4096)):
        return browse_folders(path)

    @app.get("/api/models")
    async def model_options(runtime: str | None = Query(default=None, max_length=32)):
        options = models.options(runtime)
        return {
            "models": [asdict(option) for option in options],
            "runtimes": [asdict(info) for info in app.state.service.backend.runtimes()],
        }

    @app.get("/api/runtimes")
    async def runtime_options():
        return {"runtimes": [asdict(info) for info in app.state.service.backend.runtimes()]}

    @app.post("/api/leads", status_code=201)
    async def create_lead(body: LeadBody):
        return asdict(app.state.store.create_lead(LeadCreate(**body.model_dump())))

    @app.patch("/api/leads/{lead_id}")
    async def update_lead(lead_id: str, body: LeadPatch):
        return asdict(
            app.state.store.update_lead(
                lead_id, body.revision, body.model_dump(exclude={"revision"})
            )
        )

    @app.delete("/api/leads/{lead_id}")
    async def delete_lead(
        lead_id: str,
        request: Request,
        revision: str = Query(min_length=1, max_length=19, pattern=r"^[0-9]+$"),
    ):
        # Query strings have no native integer type. Reject fractions and ambiguity
        # instead of relying on Pydantic's permissive string-to-integer coercion.
        if len(request.query_params.getlist("revision")) != 1:
            raise Invalid("Provide exactly one revision.")
        return asdict(app.state.store.delete_lead(lead_id, int(revision)))

    @app.post("/api/messages")
    async def post_human(body: MessageBody):
        return asdict(app.state.service.post_human(body.text, public_note=body.public_note))

    @app.post("/api/bridge/messages")
    async def post_bridge(body: BridgeBody, request: Request):
        return asdict(
            app.state.service.post_bridge(
                request.state.token, body.call_id, body.text, body.recipients
            )
        )

    @app.get("/api/bridge/records")
    async def bridge_records(request: Request):
        return {"records": app.state.service.list_records(request.state.token)}

    @app.get("/api/bridge/records/{name}")
    async def bridge_read_record(name: str, request: Request):
        return app.state.service.read_record(request.state.token, name)

    @app.post("/api/bridge/records")
    async def bridge_write_record(body: BridgeRecordBody, request: Request):
        return app.state.service.write_record(
            request.state.token, body.name, body.content, body.mode
        )

    @app.post("/api/room/pause")
    async def pause():
        await app.state.service.pause()
        return app.state.store.snapshot()

    @app.post("/api/room/resume")
    async def resume():
        app.state.service.resume()
        return app.state.store.snapshot()

    package = Path(__file__).resolve().parent
    # Wheels carry assets inside the package; editable checkouts use frontend/.
    static = package / "static"
    if not static.is_dir():
        static = package.parents[2] / "frontend"

    @app.get("/")
    async def index():
        return FileResponse(static / "index.html")

    @app.get("/theme.js")
    async def theme_javascript():
        return FileResponse(static / "theme.js", media_type="text/javascript")

    @app.get("/app.js")
    async def javascript():
        return FileResponse(static / "app.js", media_type="text/javascript")

    @app.get("/tasks.js")
    async def tasks_javascript():
        return FileResponse(static / "tasks.js", media_type="text/javascript")

    @app.get("/style.css")
    async def stylesheet():
        return FileResponse(static / "style.css", media_type="text/css")

    return app
