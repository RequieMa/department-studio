"""Claude Code one-shot adapter over its stream-json print interface."""

import asyncio
import json
import os
import shutil
import sys
from collections.abc import Mapping, Sequence
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from department_studio.backends.base import (
    AgentEvent,
    BackendCapabilities,
    ContextOutcome,
    ContextRequest,
    Emit,
    ModelOption,
    RunOutcome,
    RunRequest,
)
from department_studio.backends.process import LineProcess, ProcessError
from department_studio.config import Settings
from department_studio.instructions import ROOM_TOOL_MCP, agent_instructions
from department_studio.models import ModelCatalog

DISCUSS_TOOLS = ("Read", "Grep", "Glob")
DEVELOP_TOOLS = ("Read", "Edit", "Write", "Bash", "Grep", "Glob")
ROOM_BRIDGE_SERVER = "room"
RUNTIME_FAILURE = "Claude Code failed. Check the selected model and local runtime setup."
BRIDGE_FAILURE = "The room bridge did not initialize; no prompt was sent."
INIT_TIMEOUT = 30


@dataclass
class _Execution:
    process: LineProcess
    canceled: bool = False
    stop_task: asyncio.Task | None = None
    native_ref: str | None = None


class ClaudeBackend:
    def __init__(
        self,
        settings: Settings,
        catalog: ModelCatalog,
        *,
        command_prefix: Sequence[str] | None = None,
        extra_env: Mapping[str, str] | None = None,
    ):
        self.settings = settings
        self.catalog = catalog
        self._prefix = list(command_prefix or [settings.claude_executable])
        self._extra_env = dict(extra_env or {})
        self._runs: dict[str, _Execution] = {}
        self._clients: set[LineProcess] = set()
        self._closing = False

    def available(self) -> bool:
        command = self._prefix[0]
        return bool(shutil.which(command) or Path(command).is_file())

    def capabilities(self) -> BackendCapabilities:
        return BackendCapabilities(
            model_selection=True,
            local_workspace=True,
            cancellation=True,
            persistent_conversation=True,
            room_bridge=True,
            context_maintenance=False,
        )

    async def list_models(self, workspace: Path) -> list[ModelOption]:
        return self.catalog.options("claude")

    def _environment(self, request: RunRequest, selection, session_dir: Path) -> dict[str, str]:
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("DEPARTMENT_STUDIO_")
        }
        env.update(self._extra_env)
        env["DEPARTMENT_STUDIO_BRIDGE_URL"] = request.bridge_url
        env["DEPARTMENT_STUDIO_BRIDGE_TOKEN"] = request.bridge_token
        env["CLAUDE_CONFIG_DIR"] = str(session_dir)
        if selection.provider.anthropic_base_url:
            env["ANTHROPIC_BASE_URL"] = selection.provider.anthropic_base_url
        if selection.api_key:
            # DeepSeek's Anthropic-compatible endpoint documents AUTH_TOKEN.
            env["ANTHROPIC_AUTH_TOKEN"] = selection.api_key
        return env

    @staticmethod
    def _mcp_config() -> dict:
        return {
            "mcpServers": {
                ROOM_BRIDGE_SERVER: {
                    "type": "stdio",
                    "command": sys.executable,
                    "args": ["-m", "department_studio.bridge_mcp"],
                    "env": {
                        "DEPARTMENT_STUDIO_BRIDGE_URL": "${DEPARTMENT_STUDIO_BRIDGE_URL}",
                        "DEPARTMENT_STUDIO_BRIDGE_TOKEN": "${DEPARTMENT_STUDIO_BRIDGE_TOKEN}",
                    },
                }
            }
        }

    @staticmethod
    def _tools(permission: str) -> tuple[str, ...]:
        return DEVELOP_TOOLS if permission == "develop" else DISCUSS_TOOLS

    def _arguments(
        self,
        request: RunRequest,
        selection,
        mcp_config: Path,
        instructions: str,
    ) -> list[str]:
        lead = request.lead
        tools = self._tools(lead.permission)
        allowed = ",".join((*tools, ROOM_TOOL_MCP))
        arguments = [
            "-p",
            "--output-format",
            "stream-json",
            "--verbose",
            "--model",
            selection.model.id,
            "--permission-mode",
            "dontAsk",
            "--tools",
            ",".join(tools),
            "--allowedTools",
            allowed,
            "--strict-mcp-config",
            "--mcp-config",
            str(mcp_config),
            "--disable-slash-commands",
            "--append-system-prompt",
            instructions,
        ]
        if request.native_session_ref:
            arguments.extend(["--resume", request.native_session_ref])
        else:
            arguments.extend(["--session-id", lead.conversation_id])
        return arguments

    async def _await_init(self, process: LineProcess, emit: Emit) -> None:
        try:
            async with asyncio.timeout(INIT_TIMEOUT):
                while True:
                    line = await process.next_line()
                    try:
                        event = json.loads(line)
                    except (ValueError, TypeError) as exc:
                        raise ProcessError("Claude Code returned invalid protocol output.") from exc
                    if not isinstance(event, dict):
                        raise ProcessError("Claude Code returned invalid protocol output.")
                    if event.get("type") == "system" and event.get("subtype") == "init":
                        errors = event.get("mcp_server_errors") or []
                        servers = event.get("mcp_servers") or []
                        if errors:
                            raise ProcessError(BRIDGE_FAILURE)
                        if isinstance(servers, list):
                            room = next(
                                (
                                    item
                                    for item in servers
                                    if isinstance(item, dict)
                                    and item.get("name") == ROOM_BRIDGE_SERVER
                                ),
                                None,
                            )
                            if room is None or room.get("status") in {
                                "failed",
                                "error",
                                "disconnected",
                            }:
                                raise ProcessError(BRIDGE_FAILURE)
                        return
                    if event.get("type") == "error":
                        raise ProcessError(BRIDGE_FAILURE)
        except TimeoutError as exc:
            raise ProcessError(BRIDGE_FAILURE) from exc

    async def _collect(self, process: LineProcess, request: RunRequest) -> RunOutcome:
        fallback = ""
        while True:
            line = await process.next_line()
            try:
                event = json.loads(line)
            except (ValueError, TypeError) as exc:
                raise ProcessError("Claude Code returned invalid protocol output.") from exc
            if not isinstance(event, dict):
                raise ProcessError("Claude Code returned invalid protocol output.")
            kind = event.get("type")
            if kind == "assistant":
                message = event.get("message") or {}
                content = message.get("content") if isinstance(message, dict) else None
                if isinstance(content, list):
                    text = "".join(
                        block.get("text", "")
                        for block in content
                        if isinstance(block, dict)
                        and block.get("type") == "text"
                        and isinstance(block.get("text"), str)
                    )
                    if text.strip():
                        fallback = text
            elif kind == "result":
                native = event.get("session_id")
                result = event.get("result")
                if event.get("is_error") or event.get("subtype") != "success":
                    return RunOutcome("failed", error=RUNTIME_FAILURE, native_session_ref=native)
                text = result if isinstance(result, str) and result.strip() else fallback
                if not text.strip():
                    return RunOutcome("failed", error=RUNTIME_FAILURE, native_session_ref=native)
                text = text.replace(request.bridge_token, "[redacted runtime credential]")
                if len(text) > 32000:
                    text = text[:31940] + "\n[Public reply truncated at the room message limit.]"
                return RunOutcome("completed", text=text.strip(), native_session_ref=native)
            elif kind == "error":
                return RunOutcome("failed", error=RUNTIME_FAILURE)

    async def prepare_context(self, request: ContextRequest, emit: Emit) -> ContextOutcome:
        # Claude Code owns its own conversation compaction. A resume is not a
        # model request here, so idle preparation has nothing to inspect.
        return ContextOutcome("kept")

    async def run(self, request: RunRequest, emit: Emit) -> RunOutcome:
        if request.id in self._runs:
            raise ProcessError("This Claude Code delivery is already running.")
        execution = None
        process = None
        native_ref = None
        snapshots = ExitStack()
        try:
            lead = request.lead
            selection = self.catalog.require(lead.provider, lead.model_id, "claude")
            selection.require_api_key()
            instructions = agent_instructions(lead, runtime="Claude Code", room_tool=ROOM_TOOL_MCP)
            session_dir = self.settings.data_dir / "sessions" / lead.id / "claude"
            session_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            session_dir.chmod(0o700)
            temporary = snapshots.enter_context(
                TemporaryDirectory(prefix="claude-", dir=session_dir)
            )
            mcp_config = Path(temporary) / "mcp.json"
            mcp_config.write_text(json.dumps(self._mcp_config()), encoding="utf-8")
            mcp_config.chmod(0o600)
            env = self._environment(request, selection, session_dir)
            process = LineProcess(
                self._prefix + self._arguments(request, selection, mcp_config, instructions),
                cwd=Path(lead.workspace),
                env=env,
                stop_timeout=self.settings.stop_timeout_seconds * 0.6,
            )
            if self._closing:
                raise ProcessError("Claude Code backend is shutting down.")
            self._clients.add(process)
            execution = _Execution(process)
            self._runs[request.id] = execution
            await process.start()
            if execution.canceled:
                return RunOutcome("interrupted")
            await self._await_init(process, emit)
            native_ref = execution.native_ref
            if execution.canceled:
                return RunOutcome("interrupted", native_session_ref=native_ref)
            await emit(AgentEvent("started", "Claude Code runtime started."))
            await process.write_stdin(request.prompt)
            process.close_stdin()
            outcome = await self._collect(process, request)
            native_ref = outcome.native_session_ref or native_ref
            return RunOutcome(outcome.state, outcome.text, outcome.error, native_ref)
        except asyncio.CancelledError:
            if execution:
                execution.canceled = True
            raise
        except (ProcessError, OSError, ValueError, KeyError, TypeError) as exc:
            outcome = RunOutcome(
                "failed",
                error=str(exc) if isinstance(exc, (ProcessError, ValueError)) else RUNTIME_FAILURE,
            )
        finally:
            try:
                if process:
                    if not await process.close():
                        await process.process.wait()
                        await process.close()
            finally:
                if process:
                    self._clients.discard(process)
                self._runs.pop(request.id, None)
                snapshots.close()
        if execution and execution.canceled:
            return RunOutcome("interrupted", native_session_ref=native_ref)
        return RunOutcome(outcome.state, outcome.text, outcome.error, native_ref)

    async def _stop(self, execution: _Execution) -> bool:
        return await execution.process.close()

    async def cancel(self, run_id: str) -> bool:
        execution = self._runs.get(run_id)
        if not execution:
            return True
        execution.canceled = True
        if execution.stop_task is None:
            execution.stop_task = asyncio.create_task(self._stop(execution))
        return await asyncio.shield(execution.stop_task)

    async def close(self):
        self._closing = True
        for execution in self._runs.values():
            execution.canceled = True
        results = await asyncio.gather(*(process.close() for process in list(self._clients)))
        if not all(results):
            raise ProcessError("Claude Code shutdown could not confirm process exit.")
        self._clients.clear()
        self._runs.clear()
