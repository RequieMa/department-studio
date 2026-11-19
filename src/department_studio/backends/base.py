from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from department_studio.domain import Lead


@dataclass(frozen=True)
class BackendCapabilities:
    model_selection: bool
    local_workspace: bool
    cancellation: bool
    persistent_conversation: bool


@dataclass(frozen=True)
class ModelOption:
    provider: str
    id: str
    name: str


@dataclass(frozen=True)
class AgentEvent:
    kind: Literal["started", "progress", "error"]
    message: str


@dataclass(frozen=True)
class RunRequest:
    id: str
    generation: int
    lead: Lead
    prompt: str
    bridge_url: str
    bridge_token: str


@dataclass(frozen=True)
class RunOutcome:
    state: Literal["completed", "failed", "interrupted"]
    text: str = ""
    error: str | None = None
    native_session_ref: str | None = None


Emit = Callable[[AgentEvent], Awaitable[None]]


class AgentBackend(Protocol):
    def capabilities(self) -> BackendCapabilities: ...
    async def list_models(self, workspace: Path) -> list[ModelOption]: ...
    async def run(self, request: RunRequest, emit: Emit) -> RunOutcome: ...
    async def cancel(self, run_id: str) -> bool: ...
    async def close(self) -> None: ...
