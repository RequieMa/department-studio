"""DeepSeek Harness (dsh) headless adapter over its JSON event stream."""

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

RUNTIME_FAILURE = "DeepSeek Harness failed. Check the selected model and local runtime setup."
BRIDGE_FAILURE = "The room bridge did not initialize; no prompt was sent."
DSH_PROVIDER = "deepseek-official"


@dataclass
class _Execution:
    process: LineProcess
    canceled: bool = False
    stop_task: asyncio.Task | None = None


class DeepSeekBackend:
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
        self._prefix = list(command_prefix or [settings.deepseek_executable])
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
        return self.catalog.options("deepseek")

    def _environment(self, request: RunRequest, selection) -> dict[str, str]:
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("DEPARTMENT_STUDIO_")
        }
        env.update(self._extra_env)
        env["DEPARTMENT_STUDIO_BRIDGE_URL"] = request.bridge_url
        env["DEPARTMENT_STUDIO_BRIDGE_TOKEN"] = request.bridge_token
        env["DSH_PERMISSION_MODE"] = "read-only"
        if selection.provider.anthropic_base_url:
            env["DEEPSEEK_BASE_URL"] = selection.provider.anthropic_base_url
        if selection.api_key:
            env["DEEPSEEK_API_KEY"] = selection.api_key
        return env

    @staticmethod
    def _value(value) -> str:
        # JSON strings and arrays are valid YAML scalars/sequences.
        return json.dumps(value, ensure_ascii=False)

    @staticmethod
    def _template_safe(instructions: str) -> str:
        # dsh persona fields are interpolated templates. Keep literal AGENTS.md
        # braces from becoming unresolved template variables.
        return instructions.replace("{{", "{ {").replace("}}", "} }")

    def _patch(self, request: RunRequest, selection, instructions: str) -> str:
        instructions = self._template_safe(instructions)
        lines = [
            "- id: agent-default-model",
            "  config:",
            f"    provider: {self._value(DSH_PROVIDER)}",
            f"    model: {self._value(selection.model.id)}",
            "- id: system-prompt",
            "  config:",
            f"    personaSuffix: {self._value(instructions)}",
            "- id: mcp-room",
            '  name: "@deepseek-ai/dsh-mcp-client"',
            "  config:",
            '    serverName: "room"',
            '    transport: "stdio"',
            f"    command: {self._value(sys.executable)}",
            '    args: ["-m", "department_studio.bridge_mcp"]',
            "    failOnStartupError: true",
            "    env:",
            "      DEPARTMENT_STUDIO_BRIDGE_URL: !!js process.env.DEPARTMENT_STUDIO_BRIDGE_URL",
            "      DEPARTMENT_STUDIO_BRIDGE_TOKEN: !!js process.env.DEPARTMENT_STUDIO_BRIDGE_TOKEN",
        ]
        lines.extend(
            [
                "- id: tool-bash",
                "  disabled: true",
                "- id: tool-pwsh",
                "  disabled: true",
                "- id: tool-jobs",
                "  disabled: true",
                "- id: tool-fs",
                "  config:",
                "    write: false",
                "    edit: false",
                "- id: tool-web",
                "  disabled: true",
                "- id: tool-subagent",
                "  disabled: true",
                "- id: tool-workflow",
                "  disabled: true",
            ]
        )
        return "\n".join(lines) + "\n"

    def _arguments(self, request: RunRequest, patch_path: Path) -> list[str]:
        arguments = [
            "--profile",
            self.settings.deepseek_profile,
            "--patch",
            str(patch_path),
            "--json",
        ]
        if request.native_session_ref:
            arguments.extend(["--session-id", request.native_session_ref])
        arguments.append("-")
        return arguments

    async def _collect(self, process: LineProcess, request: RunRequest):
        native = request.native_session_ref
        final_text = None
        saw_session = False
        while True:
            line = await process.next_line()
            try:
                event = json.loads(line)
            except (ValueError, TypeError) as exc:
                raise ProcessError("DeepSeek Harness returned invalid protocol output.") from exc
            if not isinstance(event, dict):
                raise ProcessError("DeepSeek Harness returned invalid protocol output.")
            kind = event.get("type")
            if kind == "session":
                session_id = event.get("sessionId")
                if isinstance(session_id, str) and session_id:
                    native = session_id
                saw_session = True
            elif kind == "final":
                text = event.get("text")
                if isinstance(text, str):
                    final_text = text
                break
            elif kind == "error":
                break
        return saw_session, final_text, native

    async def prepare_context(self, request: ContextRequest, emit: Emit) -> ContextOutcome:
        return ContextOutcome("kept")

    async def run(self, request: RunRequest, emit: Emit) -> RunOutcome:
        if request.id in self._runs:
            raise ProcessError("This DeepSeek Harness delivery is already running.")
        execution = None
        process = None
        native_ref = request.native_session_ref
        snapshots = ExitStack()
        outcome = None
        try:
            lead = request.lead
            selection = self.catalog.require(lead.provider, lead.model_id, "deepseek")
            selection.require_api_key()
            records_dir = self.settings.data_dir / "records"
            records_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            records_dir.chmod(0o700)
            instructions = agent_instructions(
                lead,
                runtime="DeepSeek Harness",
                room_tool=ROOM_TOOL_MCP,
                records_path=records_dir,
            )
            session_dir = self.settings.data_dir / "sessions" / lead.id / "deepseek"
            session_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            session_dir.chmod(0o700)
            temporary = snapshots.enter_context(TemporaryDirectory(prefix="dsh-", dir=session_dir))
            patch_path = Path(temporary) / "patch.yml"
            patch_path.write_text(self._patch(request, selection, instructions), encoding="utf-8")
            patch_path.chmod(0o600)
            if self._closing:
                raise ProcessError("DeepSeek Harness backend is shutting down.")
            process = LineProcess(
                self._prefix + self._arguments(request, patch_path),
                cwd=Path(lead.workspace),
                env=self._environment(request, selection),
                stop_timeout=self.settings.stop_timeout_seconds * 0.6,
            )
            self._clients.add(process)
            execution = _Execution(process)
            self._runs[request.id] = execution
            await process.start()
            if execution.canceled:
                return RunOutcome("interrupted")
            await process.write_stdin(request.prompt)
            process.close_stdin()
            await emit(AgentEvent("started", "DeepSeek Harness runtime started."))
            saw_session, final_text, native_ref = await self._collect(process, request)
            exited = await process.wait_exit(30)
            if not exited:
                await process.close()
                return RunOutcome(
                    "failed",
                    error="DeepSeek Harness did not exit after its final event.",
                    native_session_ref=native_ref,
                )
            if execution.canceled:
                return RunOutcome("interrupted", native_session_ref=native_ref)
            if process.returncode != 0 or not saw_session or final_text is None:
                return RunOutcome("failed", error=RUNTIME_FAILURE, native_session_ref=native_ref)
            if not final_text.strip():
                return RunOutcome("failed", error=RUNTIME_FAILURE, native_session_ref=native_ref)
            text = final_text.replace(request.bridge_token, "[redacted runtime credential]")
            if len(text) > 32000:
                text = text[:31940] + "\n[Public reply truncated at the room message limit.]"
            return RunOutcome("completed", text=text.strip(), native_session_ref=native_ref)
        except asyncio.CancelledError:
            if execution:
                execution.canceled = True
            raise
        except (ProcessError, OSError, ValueError, KeyError, TypeError) as exc:
            outcome = RunOutcome(
                "failed",
                error=str(exc) if isinstance(exc, (ProcessError, ValueError)) else RUNTIME_FAILURE,
                native_session_ref=native_ref,
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
        return outcome

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
            raise ProcessError("DeepSeek Harness shutdown could not confirm process exit.")
        self._clients.clear()
        self._runs.clear()
