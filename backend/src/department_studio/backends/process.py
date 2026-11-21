"""Bounded JSONL/line subprocess transport for one-shot agent runtimes."""

import asyncio
import os
import signal
from collections.abc import Mapping, Sequence
from pathlib import Path

MAX_LINE_BYTES = 2 * 1024 * 1024


class ProcessError(RuntimeError):
    """A public, sanitized runtime-process failure."""


class LineProcess:
    """A child whose stdout is newline-delimited text.

    Stderr is drained and discarded. The host never copies native stderr,
    credentials or provider payloads into a public error message.
    """

    def __init__(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str] | None,
        stop_timeout: float = 4,
        max_line: int = MAX_LINE_BYTES,
    ):
        self.argv = list(argv)
        self.cwd = Path(cwd)
        self.env = dict(env) if env is not None else None
        self.stop_timeout = stop_timeout
        self.max_line = max_line
        self.process: asyncio.subprocess.Process | None = None
        self.stderr_bytes = 0
        self._lines: asyncio.Queue = asyncio.Queue(maxsize=512)
        self._failure: ProcessError | None = None
        self._start_task: asyncio.Task | None = None
        self._readers: list[asyncio.Task] = []
        self._close_lock = asyncio.Lock()
        self._stdin_closed = False
        self._closing = False

    @property
    def returncode(self) -> int | None:
        return self.process.returncode if self.process else None

    async def start(self):
        if self._closing or self._start_task:
            raise ProcessError("Agent runtime cannot start again.")
        self._start_task = asyncio.create_task(
            asyncio.create_subprocess_exec(
                *self.argv,
                cwd=self.cwd,
                env=self.env,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
                limit=self.max_line + 1,
            )
        )
        try:
            self.process = await asyncio.shield(self._start_task)
        except OSError as exc:
            raise ProcessError(
                "The agent runtime could not start. Check its executable and workspace."
            ) from exc
        except asyncio.CancelledError:
            await self.close()
            raise
        self._readers = [
            asyncio.create_task(self._read_stdout()),
            asyncio.create_task(self._drain_stderr()),
        ]
        if self._closing:
            raise ProcessError("Agent runtime stopped during startup.")

    def _fail(self, message: str):
        if self._failure:
            return
        self._failure = ProcessError(message)
        try:
            self._lines.put_nowait(None)
        except asyncio.QueueFull:
            pass

    async def _read_stdout(self):
        try:
            while True:
                try:
                    raw = await self.process.stdout.readline()
                except (ValueError, asyncio.LimitOverrunError):
                    self._fail("Agent runtime returned an oversized output line.")
                    return
                except OSError:
                    self._fail("Agent runtime output could not be read.")
                    return
                if not raw:
                    break
                if len(raw) > self.max_line:
                    self._fail("Agent runtime returned an oversized output line.")
                    return
                await self._lines.put(raw.decode("utf-8", "replace").removesuffix("\n"))
            if self.process.returncode is None:
                # A closed stdout is not proof of a completed run; keep the
                # stream open until exit or a caller-requested close.
                await self.process.wait()
        except asyncio.CancelledError:
            raise
        finally:
            try:
                self._lines.put_nowait(None)
            except asyncio.QueueFull:
                pass

    async def _drain_stderr(self):
        try:
            while chunk := await self.process.stderr.read(65536):
                self.stderr_bytes += len(chunk)
        except (OSError, asyncio.CancelledError):
            pass

    async def write_stdin(self, text: str):
        if not self.process or self.process.returncode is not None:
            raise ProcessError("Agent runtime is no longer available.")
        if self._stdin_closed:
            raise ProcessError("Agent runtime input is already closed.")
        try:
            self.process.stdin.write(text.encode("utf-8"))
            await self.process.stdin.drain()
        except (OSError, RuntimeError) as exc:
            raise ProcessError("Agent runtime input could not be written.") from exc

    def close_stdin(self):
        self._stdin_closed = True
        if self.process and self.process.stdin and not self.process.stdin.is_closing():
            self.process.stdin.close()

    async def next_line(self) -> str:
        if self._lines.empty() and self._failure:
            raise ProcessError(str(self._failure))
        line = await self._lines.get()
        if line is None:
            if self._failure:
                raise ProcessError(str(self._failure))
            raise ProcessError("Agent runtime output ended before the run completed.")
        return line

    async def _wait_exit(self, seconds: float) -> bool:
        if not self.process:
            return True
        try:
            await asyncio.wait_for(self.process.wait(), seconds)
            return True
        except TimeoutError:
            return False

    def _signal(self, sig: int):
        if not self.process:
            return
        try:
            os.killpg(self.process.pid, sig)
        except OSError:
            pass

    async def close(self) -> bool:
        """Close input and terminate the process group; true means confirmed exit."""
        async with self._close_lock:
            self._closing = True
            if self.process is None and self._start_task:
                try:
                    self.process = await asyncio.shield(self._start_task)
                except (OSError, asyncio.CancelledError):
                    return True
            if self.process is None:
                return True
            self.close_stdin()
            stopped = await self._wait_exit(self.stop_timeout / 3)
            if not stopped:
                self._signal(signal.SIGTERM)
                stopped = await self._wait_exit(self.stop_timeout / 3)
            if not stopped:
                self._signal(signal.SIGKILL)
                stopped = await self._wait_exit(self.stop_timeout / 3)
            for reader in self._readers:
                reader.cancel()
            await asyncio.gather(*self._readers, return_exceptions=True)
            return stopped

    async def wait_exit(self, seconds: float) -> bool:
        return await self._wait_exit(seconds)
