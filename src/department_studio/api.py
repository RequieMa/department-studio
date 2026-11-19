"""Authenticated local HTTP boundary for the runtime-neutral room service."""

from contextlib import ExitStack, asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from department_studio.backends.base import AgentBackend
from department_studio.backends.pi import PiBackend
from department_studio.config import DataDirectory, Settings
from department_studio.domain import Conflict, Invalid, LeadCreate, NotFound, workspace_path
from department_studio.security import OwnerCredential, allowed_request
from department_studio.service import RoomService
from department_studio.store import Store

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
    workspace: str = Field(max_length=4096)
    enabled: bool = True
    permission: Literal["discuss", "develop"] = "discuss"
    backend_kind: Literal["pi"] = "pi"


class LeadPatch(LeadBody):
    enabled: bool
    permission: Literal["discuss", "develop"]
    revision: int = Field(ge=1)


class MessageBody(StrictBody):
    text: str = Field(min_length=1, max_length=32000)


class BridgeBody(MessageBody):
    call_id: str = Field(min_length=1, max_length=200)
    recipients: list[str] = Field(default_factory=list, max_length=64)


def create_app(
    settings: Settings,
    *,
    store: Store | None = None,
    backend: AgentBackend | None = None,
    owner_token: str | None = None,
) -> FastAPI:
    owner = OwnerCredential(owner_token) if owner_token else OwnerCredential()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        with ExitStack() as stack:
            active_store = store
            if active_store is None:
                stack.enter_context(DataDirectory(settings.data_dir))
                active_store = stack.enter_context(
                    Store(
                        settings.data_dir / "room.sqlite",
                        max_chain_deliveries=settings.max_chain_deliveries,
                    )
                )
            service = RoomService(active_store, backend or PiBackend(settings), settings)
            app.state.store = active_store
            app.state.service = service
            await service.start()
            try:
                yield
            finally:
                await service.close()
                if not service.shutdown_confirmed:
                    raise RuntimeError(
                        "Shutdown could not confirm runtime stop. Inspect local processes."
                    )

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.owner = owner

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
            bridge = request.url.path == "/api/bridge/messages"
            if (bridge and not is_runtime) or (not bridge and not is_owner):
                return reject(403, "This credential cannot perform that action.")
            request.state.token = token
        response = await call_next(request)
        response.headers.update(SECURITY_HEADERS)
        return response

    @app.exception_handler(Invalid)
    async def invalid_handler(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.exception_handler(Conflict)
    async def conflict_handler(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(NotFound)
    async def missing_handler(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=404)

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

    @app.get("/api/models")
    async def models(workspace: str):
        directory = Path(workspace_path(workspace))
        try:
            options = await app.state.service.backend.list_models(directory)
        except Exception:
            return JSONResponse(
                {
                    "detail": "Pi model listing failed. Check the local Pi configuration "
                    "and provider authentication."
                },
                status_code=503,
            )
        return {"models": [asdict(option) for option in options]}

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

    @app.post("/api/messages")
    async def post_human(body: MessageBody):
        return asdict(app.state.service.post_human(body.text))

    @app.post("/api/bridge/messages")
    async def post_bridge(body: BridgeBody, request: Request):
        return asdict(
            app.state.service.post_bridge(
                request.state.token, body.call_id, body.text, body.recipients
            )
        )

    @app.post("/api/room/pause")
    async def pause():
        await app.state.service.pause()
        return app.state.store.snapshot()

    @app.post("/api/room/resume")
    async def resume():
        app.state.service.resume()
        return app.state.store.snapshot()

    static = Path(__file__).resolve().parent / "static"

    @app.get("/")
    async def index():
        return FileResponse(static / "index.html")

    @app.get("/app.js")
    async def javascript():
        return FileResponse(static / "app.js", media_type="text/javascript")

    @app.get("/style.css")
    async def stylesheet():
        return FileResponse(static / "style.css", media_type="text/css")

    return app
