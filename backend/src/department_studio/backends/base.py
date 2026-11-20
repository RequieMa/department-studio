from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from department_studio.domain import Lead

COMPACTING = "Runtime is compacting conversation history."
COMPACTION_FAILED = "Conversation compaction failed; inspect retained work before retrying."
COMPACTION_INTERRUPTED = "Conversation compaction was interrupted."

# Only these adapter diagnostics may pass through to the public room verbatim.
SAFE_DIAGNOSTICS = {
    ("progress", COMPACTING),
    ("error", COMPACTION_FAILED),
    ("error", COMPACTION_INTERRUPTED),
    ("error", "Unsupported runtime dialog canceled."),
}


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


@dataclass(frozen=True)
class ContextRequest:
    """An idle conversation check; never an instruction to resume previous work."""

    id: str
    lead: Lead


@dataclass(frozen=True)
class ContextOutcome:
    # reset asks the core to allocate a fresh conversation, retaining the old one.
    # Like run(), prepare_context() returns only after confirmed child exit.
    action: Literal["kept", "compacted", "reset", "failed", "interrupted"]
    native_session_ref: str | None = None
    reason: Literal["over_limit", "compaction_failed", "unmeasurable"] | None = None


Emit = Callable[[AgentEvent], Awaitable[None]]


class AgentBackend(Protocol):
    def capabilities(self) -> BackendCapabilities: ...
    async def list_models(self, workspace: Path) -> list[ModelOption]: ...
    async def prepare_context(self, request: ContextRequest, emit: Emit) -> ContextOutcome: ...
    async def run(self, request: RunRequest, emit: Emit) -> RunOutcome: ...
    async def cancel(self, run_id: str) -> bool: ...
    async def close(self) -> None: ...
