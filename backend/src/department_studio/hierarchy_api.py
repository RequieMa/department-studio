"""Owner-only department hierarchy graph."""

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

router = APIRouter()


class EdgeBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    a: str = Field(min_length=1, max_length=200)
    b: str = Field(min_length=1, max_length=200)
    connected: bool


@router.get("/api/hierarchy")
async def hierarchy(request: Request):
    return request.app.state.store.hierarchy()


@router.put("/api/hierarchy/edges")
async def set_edge(body: EdgeBody, request: Request):
    return request.app.state.store.set_hierarchy_edge(body.a, body.b, body.connected)


@router.post("/api/hierarchy/connect-all")
async def connect_all(request: Request):
    return request.app.state.store.connect_all_departments()
