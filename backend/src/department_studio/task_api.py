"""Task and human-decision routes under the existing owner-only /api boundary."""

from typing import Literal

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, ConfigDict, Field

router = APIRouter()


class TaskBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ChildBody(TaskBody):
    parent_id: str = Field(min_length=1, max_length=200)
    parent_revision: int = Field(ge=1)
    owner_lead_id: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=120)
    context: str = Field(default="", max_length=8000)
    idempotency_key: str = Field(min_length=1, max_length=128)


class TaskPatch(TaskBody):
    task_revision: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=120)
    context: str | None = Field(default=None, max_length=8000)
    lifecycle: Literal["open", "closed"] | None = None


class InstructionBody(TaskBody):
    text: str = Field(min_length=1, max_length=32000)
    task_revision: int = Field(ge=1)
    idempotency_key: str = Field(min_length=1, max_length=128)
    mode: Literal["execute", "record_note"]


class Choice(TaskBody):
    id: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=300)


class ActionBody(TaskBody):
    question: str = Field(min_length=1, max_length=2000)
    options: list[Choice] = Field(min_length=2, max_length=8)
    source_message_id: str | None = Field(default=None, min_length=1, max_length=200)
    task_revision: int = Field(ge=1)
    idempotency_key: str = Field(min_length=1, max_length=128)


class ResolutionBody(TaskBody):
    option_id: str = Field(min_length=1, max_length=64)
    revision: int = Field(ge=1)
    task_revision: int = Field(ge=1)
    idempotency_key: str = Field(min_length=1, max_length=128)
    mode: Literal["execute", "record_note"]


@router.get("/api/tasks")
async def tasks(
    request: Request, cursor: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=200)
):
    return request.app.state.store.list_tasks(cursor=cursor, limit=limit)


@router.get("/api/tasks/{task_id}")
async def task_detail(
    task_id: str,
    request: Request,
    cursor: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
):
    return request.app.state.store.task_detail(task_id, cursor=cursor, limit=limit)


@router.post("/api/tasks", status_code=201)
async def child(body: ChildBody, request: Request):
    return request.app.state.store.create_task(**body.model_dump())


@router.patch("/api/tasks/{task_id}")
async def patch_task(task_id: str, body: TaskPatch, request: Request):
    return request.app.state.store.update_task(
        task_id, body.task_revision, body.model_dump(exclude={"task_revision"}, exclude_unset=True)
    )


@router.post("/api/tasks/{task_id}/instructions", status_code=201)
async def instruction(task_id: str, body: InstructionBody, request: Request):
    return request.app.state.service.post_task_instruction(task_id, **body.model_dump())


@router.get("/api/action-requests")
async def actions(
    request: Request, cursor: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=200)
):
    return request.app.state.store.list_action_requests(cursor=cursor, limit=limit)


@router.post("/api/tasks/{task_id}/action-requests", status_code=201)
async def action(task_id: str, body: ActionBody, request: Request):
    return request.app.state.store.create_action_request(task_id, **body.model_dump())


@router.post("/api/action-requests/{request_id}/resolve")
async def resolution(request_id: str, body: ResolutionBody, request: Request):
    return request.app.state.service.resolve_action_request(request_id, **body.model_dump())
