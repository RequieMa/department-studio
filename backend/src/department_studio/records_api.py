"""Owner record browsing and creation; runtime credentials use /api/bridge/records."""

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

router = APIRouter()


class RecordBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(min_length=1, max_length=128)
    content: str = Field(min_length=1, max_length=524288)


class RecordReplace(RecordBody):
    mode: str = Field(default="replace", pattern="^(append|replace)$")


@router.get("/api/records")
async def list_records(request: Request):
    records = request.app.state.records
    return {"path": str(records.root), "records": records.list()}


@router.get("/api/records/{name}")
async def read_record(name: str, request: Request):
    return request.app.state.records.read(name)


@router.post("/api/records", status_code=201)
async def create_record(body: RecordBody, request: Request):
    result = request.app.state.records.write(body.name, body.content, "create")
    return result


@router.put("/api/records/{name}")
async def update_record(name: str, body: RecordReplace, request: Request):
    return request.app.state.records.write(name, body.content, body.mode)
