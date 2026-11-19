import asyncio
import os
from pathlib import Path

import pytest

from department_studio.backends.rpc import RpcError, RpcProcess

ROOT = Path(__file__).resolve().parents[1]
FAKE_PI = [
    "uv",
    "run",
    "--project",
    str(ROOT),
    "--no-sync",
    "python",
    str(ROOT / "tests/fixtures/fake_pi.py"),
]


@pytest.fixture
async def rpc(tmp_path):
    process = RpcProcess(FAKE_PI, cwd=tmp_path, command_timeout=2, stop_timeout=0.3)
    await process.start()
    yield process
    assert await process.close()


async def test_split_utf8_crlf_unicode_separators_and_correlated_ids(rpc):
    assert await rpc.command("echo") == {"text": "星图\u2028line\u2029paragraph"}


async def test_commands_can_be_pending_concurrently(rpc):
    results = await asyncio.gather(*(rpc.command("echo") for _ in range(5)))
    assert all(r["text"].startswith("星图") for r in results)


@pytest.mark.parametrize("command", ["malformed", "eof", "reject"])
async def test_protocol_errors_fail_promptly_without_raw_payloads(rpc, command):
    with pytest.raises(RpcError) as error:
        await rpc.command(command)
    assert "should-never-leak" not in str(error.value)
    assert "not-json" not in str(error.value)


async def test_drains_large_stderr_without_retaining_secret_contents(rpc):
    assert await rpc.command("stderr") == {"drained": True}
    assert rpc.stderr_bytes > 65536
    assert "secret stderr" not in repr(vars(rpc))


async def test_command_timeout_is_bounded_and_close_confirms_exit(rpc):
    with pytest.raises(RpcError, match="timed out"):
        await rpc.command("never", timeout=0.03)
    assert await rpc.close()
    assert rpc.process.returncode is not None


async def test_missing_executable_reports_sanitized_startup_error(tmp_path):
    rpc = RpcProcess([str(tmp_path / "missing-pi")], cwd=tmp_path)
    with pytest.raises(RpcError, match="start"):
        await rpc.start()
    assert await rpc.close()


async def test_permission_denied_termination_remains_unconfirmed(tmp_path, monkeypatch):
    rpc = RpcProcess(
        FAKE_PI, cwd=tmp_path, stop_timeout=0.09, env={**os.environ, "FAKE_PI_MODE": "stubborn"}
    )
    await rpc.start()
    await rpc.command("get_state")

    def denied(*args):
        raise PermissionError("Synthetic denial")

    try:
        with monkeypatch.context() as context:
            context.setattr(os, "killpg", denied)
            assert await rpc.close() is False
            assert rpc.process.returncode is None
    finally:
        assert await rpc.close()


async def test_event_consumers_do_not_hang_after_transport_failure(rpc):
    with pytest.raises(RpcError):
        await rpc.command("eof")
    with pytest.raises(RpcError):
        await rpc.next_event()
    async with asyncio.timeout(0.05):
        with pytest.raises(RpcError):
            await rpc.next_event()
