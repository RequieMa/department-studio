"""Runtime-neutral records and validation. No HTTP or agent-runtime dependencies."""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


class Invalid(ValueError):
    """Invalid user-supplied data."""


class Conflict(ValueError):
    """A valid operation conflicts with the current application state."""


class NotFound(ValueError):
    """A requested application record does not exist."""


def workspace_path(value: str | Path) -> str:
    try:
        if isinstance(value, str) and not value.strip():
            raise ValueError
        path = Path(value).expanduser().resolve(strict=True)
        if not path.is_dir():
            raise ValueError
    except (OSError, ValueError, TypeError, RuntimeError) as exc:
        raise Invalid("Workspace must be an existing local directory.") from exc
    return str(path)


def message_text(value: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 32000:
        raise Invalid("Message text must contain 1–32000 characters.")
    return value


def normalize_handle(value: str) -> str:
    if not isinstance(value, str):
        raise Invalid("A handle must be text.")
    handle = value.strip().lower()
    if not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", handle):
        raise Invalid("Handles start with a letter and use up to 32 letters, digits, _ or -.")
    return handle


@dataclass(frozen=True)
class LeadCreate:
    name: str
    handle: str
    role: str
    provider: str
    model_id: str
    workspace: str
    worker_provider: str = ""
    worker_model_id: str = ""
    enabled: bool = True
    backend_kind: Literal["pi", "claude", "deepseek"] = "pi"

    def __post_init__(self):
        for field, limit in (("name", 80), ("role", 8000), ("provider", 200), ("model_id", 200)):
            value = getattr(self, field)
            if not isinstance(value, str) or not 1 <= len(value.strip()) <= limit:
                raise Invalid(f"{field} must contain 1–{limit} characters.")
            object.__setattr__(self, field, value.strip())
        for field in ("worker_provider", "worker_model_id"):
            value = getattr(self, field)
            if not isinstance(value, str):
                raise Invalid(f"{field} must be text.")
            if len(value.strip()) > 200:
                raise Invalid(f"{field} must contain at most 200 characters.")
            object.__setattr__(self, field, value.strip())
        if bool(self.worker_provider) != bool(self.worker_model_id):
            raise Invalid("Worker provider and worker model must be set together.")
        handle = normalize_handle(self.handle)
        if handle in {"all", "you", "system"}:
            raise Invalid("That handle is reserved.")
        object.__setattr__(self, "handle", handle)
        object.__setattr__(self, "workspace", workspace_path(self.workspace))
        if type(self.enabled) is not bool:
            raise Invalid("enabled must be a boolean.")
        if self.backend_kind not in {"pi", "claude", "deepseek"}:
            raise Invalid("Choose the Pi, Claude Code or DeepSeek Harness runtime.")


@dataclass(frozen=True, kw_only=True)
class Lead(LeadCreate):
    id: str
    conversation_id: str
    revision: int
    status: str = "idle"
    deleted_at: str | None = None

    def __post_init__(self):
        # Persisted settings remain readable if a workspace later disappears.
        # Creation and updates are validated using LeadCreate.
        pass


@dataclass(frozen=True)
class LeadDeletion:
    id: str
    revision: int
    deleted_at: str


@dataclass(frozen=True)
class ContextCheck:
    id: str
    lead_id: str
    conversation_id: str
    state: str
    detail: str


@dataclass(frozen=True)
class RoomMessage:
    id: str
    sequence: int
    sender_kind: str
    sender_id: str | None
    sender_name: str
    sender_handle: str
    text: str
    recipient_ids: list[str]
    recipient_handles: list[str]
    chain_id: str | None
    timestamp: str
    notice: str | None = None


@dataclass(frozen=True)
class Receipt:
    message_id: str
    recipient_ids: list[str]
    notice: str | None = None


@dataclass(frozen=True)
class Chain:
    id: str
    root_message_id: str | None
    reserved: int
    allowance: int


@dataclass(frozen=True)
class Delivery:
    id: str
    chain_id: str
    message_id: str
    lead_id: str
    conversation_id: str
    generation: int
    state: str
    created_at: str
    started_at: str | None
    finished_at: str | None
    error: str | None
    native_session_ref: str | None
    diagnostic: str | None
