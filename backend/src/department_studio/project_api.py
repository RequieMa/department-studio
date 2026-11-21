"""Owner-only project history, creation, switching and deletion."""

from dataclasses import asdict

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from department_studio.domain import Invalid

router = APIRouter()


class ProjectBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(min_length=1, max_length=80)


def _payload(manager) -> dict:
    active = manager.project
    return {
        "projects": [asdict(project) for project in manager.projects()],
        "active_id": active.id,
    }


def _sync(app) -> None:
    app.state.store = app.state.projects.store
    app.state.service = app.state.projects.service
    app.state.records = app.state.projects.records


@router.get("/api/projects")
async def projects(request: Request):
    return _payload(request.app.state.projects)


@router.post("/api/projects", status_code=201)
async def create_project(body: ProjectBody, request: Request):
    manager = request.app.state.projects
    info = await manager.create(body.name)
    _sync(request.app)
    return {**_payload(manager), "project": asdict(info)}


@router.post("/api/projects/{project_id}/activate")
async def activate_project(project_id: str, request: Request):
    manager = request.app.state.projects
    info = await manager.switch(project_id)
    _sync(request.app)
    return {**_payload(manager), "project": asdict(info)}


@router.delete("/api/projects/{project_id}")
async def delete_project(
    project_id: str,
    request: Request,
    confirm_name: str = Query(min_length=1, max_length=80),
):
    manager = request.app.state.projects
    info = manager.info(project_id)
    if confirm_name.strip().casefold() != info.name.casefold():
        raise Invalid("Type the project name exactly to confirm deletion.")
    await manager.delete(project_id)
    return _payload(manager)
