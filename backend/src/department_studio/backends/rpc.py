"""Strict JSONL subprocess transport. Native payloads never appear in error messages."""

import asyncio
import json
import os
import signal
from collections.abc import Mapping, Sequence
from pathlib import Path
from uuid import uuid4


class RpcError(RuntimeError):
    """A public, sanitized transport failure."""


class RpcTimeout(RpcError):
    """A command deadline, with only allowlisted command/phase diagnostics."""

    def __init__(self, command: str, phase: str):
        safe_command = (
            command
            if command
            in {
                "get_state",
                "get_available_models",
                "get_session_stats",
                "get_messages",
                "compact",
                "prompt",
                "clear_queue",
                "abort",
            }
            else "command"
        )
        detail = f"Pi command timed out while {phase} ({safe_command})."
        if command == "prompt":
            detail += (
                " Prompt acceptance is unknown; inspect retained work before sending a new request."
            )
        super().__init__(detail)


class RpcProcess:
    def __init__(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str] | None = None,
        command_timeout: float = 10,
        stop_timeout: float = 3,
    ):
        self.argv = list(argv)
        self.cwd = cwd
        self.env = env
        self.command_timeout = command_timeout
        self.stop_timeout = stop_timeout
        self.process: asyncio.subprocess.Process | None = None
        self.stderr_bytes = 0
        self._pending: dict[str, tuple[str, asyncio.Future]] = {}
        self._events: asyncio.Queue = asyncio.Queue(maxsize=1024)
        self._failure: RpcError | None = None
        self._start_task: asyncio.Task | None = None
        self._readers: list[asyncio.Task] = []
        self._close_lock = asyncio.Lock()
        self._write_lock = asyncio.Lock()
        self._closing = False

    async def start(self):
        if self._closing or self._start_task:
            raise RpcError("Pi transport cannot start again.")
        self._start_task = asyncio.create_task(
            asyncio.create_subprocess_exec(
                *self.argv,
                cwd=self.cwd,
                env=self.env,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            )
        )
        try:
            self.process = await asyncio.shield(self._start_task)
        except OSError as exc:
            raise RpcError("Pi could not start. Check its executable and workspace.") from exc
        except asyncio.CancelledError:
            # A canceled spawn await can still leave a live child; retain and stop it.
            await self.close()
            raise
        self._attach_readers()
        if self._closing:
            raise RpcError("Pi stopped during startup.")

    def _attach_readers(self):
        if not self._readers:
            self._readers = [
                asyncio.create_task(self._read_stdout()),
                asyncio.create_task(self._drain_stderr()),
            ]

    def _fail(self, message: str):
        if self._failure:
            return
        self._failure = RpcError(message)
        for _, future in self._pending.values():
            if not future.done():
                future.set_exception(RpcError(message))
        if not self._events.full():
            self._events.put_nowait(None)

    async def _read_stdout(self):
        buffer = bytearray()
        try:
            while chunk := await self.process.stdout.read(65536):
                buffer.extend(chunk)
                while (end := buffer.find(b"\n")) >= 0:
                    record = bytes(buffer[:end]).removesuffix(b"\r")
                    del buffer[: end + 1]
                    if len(record) > 8 * 1024 * 1024:
                        raise ValueError
                    value = json.loads(record.decode("utf-8"))
                    if not isinstance(value, dict) or not isinstance(value.get("type"), str):
                        raise ValueError
                    if value["type"] == "response":
                        pending = self._pending.get(value.get("id"))
                        if pending:
                            command, future = pending
                            if value.get("command") != command:
                                raise ValueError
                            if not future.done():
                                future.set_result(value)
                    else:
                        self._events.put_nowait(value)
                if len(buffer) > 8 * 1024 * 1024:
                    raise ValueError
            self._fail("Pi output ended before the operation completed.")
        except (ValueError, UnicodeError, asyncio.QueueFull, TypeError):
            self._fail("Pi returned invalid or excessive protocol output.")
        except OSError:
            self._fail("Pi output could not be read.")

    async def _drain_stderr(self):
        try:
            while chunk := await self.process.stderr.read(65536):
                self.stderr_bytes += len(chunk)
        except OSError:
            pass

    async def send(self, record: dict):
        if not self.process or self.process.returncode is not None or self._failure:
            raise RpcError("Pi is no longer available.")
        try:
            async with self._write_lock:
                self.process.stdin.write((json.dumps(record, ensure_ascii=False) + "\n").encode())
                await self.process.stdin.drain()
        except (OSError, RuntimeError) as exc:
            raise RpcError("Pi input could not be written.") from exc

    async def command(
        self,
        command: str,
        *,
        timeout: float | None = None,  # noqa: ASYNC109 -- per-command RPC deadline
        response_activity: asyncio.Event | None = None,
        activity_timeout: float | None = None,
        **arguments,
    ):
        request_id = uuid4().hex
        loop = asyncio.get_running_loop()
        started = loop.time()
        future = loop.create_future()
        self._pending[request_id] = (command, future)
        activity_waiter = None
        try:
            phase = "writing input"
            try:
                # Include lock acquisition and stdin backpressure, not just the response.
                budget = self.command_timeout if timeout is None else timeout
                async with asyncio.timeout(budget) as deadline:
                    await self.send({"id": request_id, "type": command, **arguments})
                    phase = "waiting for response"
                    if response_activity is not None and activity_timeout is not None:
                        activity_waiter = asyncio.create_task(response_activity.wait())
                        done, _ = await asyncio.wait(
                            {future, activity_waiter}, return_when=asyncio.FIRST_COMPLETED
                        )
                        if future not in done:
                            # Pi can compact before acknowledging a prompt. A real compaction
                            # event admits the remaining run budget once; it never extends
                            # input writes or turns arbitrary output into a keepalive.
                            phase = "compacting conversation history before response"
                            deadline.reschedule(started + max(budget, activity_timeout))
                    response = await future
            except TimeoutError as exc:
                raise RpcTimeout(command, phase) from exc
            if response.get("success") is not True:
                raise RpcError(
                    "Pi rejected the command. Check the selected model and runtime setup."
                )
            return response.get("data")
        finally:
            if activity_waiter is not None:
                activity_waiter.cancel()
            self._pending.pop(request_id, None)
            if not future.done():
                future.cancel()
            elif not future.cancelled():
                # A reader failure may race an interrupted stdin drain. Retrieve it even
                # when the caller never reached its response await.
                future.exception()
            if activity_waiter is not None:
                await asyncio.gather(activity_waiter, return_exceptions=True)

    async def next_event(self) -> dict:
        if self._events.empty() and self._failure:
            raise RpcError(str(self._failure))
        event = await self._events.get()
        if event is None:
            raise RpcError(str(self._failure or "Pi output ended."))
        return event

    async def _wait_exit(self, seconds: float) -> bool:
        try:
            await asyncio.wait_for(self.process.wait(), seconds)
            return True
        except TimeoutError:
            return False

    def _signal(self, sig: int):
        try:
            os.killpg(self.process.pid, sig)
        except OSError:
            # A denied signal is not evidence of exit. The subsequent wait determines that.
            pass

    async def close(self) -> bool:
        """Close input, then terminate the process group; true requires confirmed child exit."""
        async with self._close_lock:
            self._closing = True
            if self.process is None and self._start_task:
                try:
                    self.process = await asyncio.shield(self._start_task)
                    self._attach_readers()
                except OSError:
                    return True
            if self.process is None:
                return True
            if self.process.stdin:
                self.process.stdin.close()
            stopped = await self._wait_exit(self.stop_timeout / 3)
            if not stopped:
                self._signal(signal.SIGTERM)
                stopped = await self._wait_exit(self.stop_timeout / 3)
            if not stopped:
                self._signal(signal.SIGKILL)
                stopped = await self._wait_exit(self.stop_timeout / 3)
            if stopped:
                # Detached descendants can retain pipe handles even after Pi exits.
                for reader in self._readers:
                    reader.cancel()
                await asyncio.gather(*self._readers, return_exceptions=True)
                self._fail("Pi transport closed.")
            return stopped
