import asyncio

import pytest

from department_studio.backends.rpc import RpcError
from tests.test_pi import backend_factory as backend_factory
from tests.test_pi import no_events, records
from tests.test_pi import request_factory as request_factory
from tests.test_rpc import rpc as rpc


async def test_deadline_includes_waiting_for_input_lock(rpc):
    # A blocked transport write must not escape the command deadline.
    async with rpc._write_lock:
        async with asyncio.timeout(0.3):
            with pytest.raises(RpcError, match="timed out"):
                await rpc.command("echo", timeout=0.02)
    assert rpc._pending == {}
    assert (await rpc.command("echo"))["text"].startswith("星图")


async def test_deadline_includes_stdin_backpressure(rpc, monkeypatch):
    async def blocked_drain():
        await asyncio.Event().wait()

    monkeypatch.setattr(rpc.process.stdin, "drain", blocked_drain)
    async with asyncio.timeout(0.3):
        with pytest.raises(RpcError, match="writing"):
            await rpc.command("echo", timeout=0.02)
    assert rpc._pending == {}


async def test_timeout_identifies_safe_phase_without_echoing_untrusted_command(rpc):
    with pytest.raises(RpcError) as failure:
        await rpc.command("never", timeout=0.02, message="private prompt value")
    assert "response" in str(failure.value)
    assert "private prompt value" not in str(failure.value)
    assert rpc._pending == {}


async def test_canceling_pending_command_cleans_waiters(rpc):
    async with rpc._write_lock:
        command = asyncio.create_task(rpc.command("echo"))
        await asyncio.sleep(0)
        command.cancel()
        with pytest.raises(asyncio.CancelledError):
            await command
    assert rpc._pending == {}


def short_commands(backend):
    original = backend._client

    def client(*args, **kwargs):
        rpc = original(*args, **kwargs)
        rpc.command_timeout = 0.3
        return rpc

    backend._client = client


async def test_dialog_before_prompt_ack_does_not_deadlock(
    backend_factory, request_factory, tmp_path
):
    backend = backend_factory("dialog_before_ack")
    short_commands(backend)
    events = []

    async def capture(event):
        events.append(event)

    outcome = await backend.run(request_factory(), capture)
    assert outcome.state == "completed"
    assert any("dialog" in event.message for event in events)
    trace = records(tmp_path)
    assert len([entry for entry in trace if entry.get("type") == "prompt"]) == 1
    response = next(entry for entry in trace if entry.get("type") == "extension_ui_response")
    assert response["cancelled"] is True
    assert backend._clients == set() and backend._runs == {}


async def test_completion_before_ack_is_retained(backend_factory, request_factory):
    backend = backend_factory("finished_before_ack")
    short_commands(backend)
    outcome = await backend.run(request_factory(), no_events)
    assert outcome.state == "completed" and outcome.text == "Synthetic public reply"
    assert backend._clients == set() and backend._runs == {}


async def test_state_timeout_identifies_command_and_never_prompts(
    backend_factory, request_factory, tmp_path
):
    backend = backend_factory("silent_state")
    short_commands(backend)
    outcome = await backend.run(request_factory(), no_events)
    assert outcome.state == "failed" and "get_state" in outcome.error
    assert not any(entry.get("type") == "prompt" for entry in records(tmp_path))
    assert backend._clients == set() and backend._runs == {}


@pytest.mark.parametrize("mode", ["silent_prompt", "finished_without_ack"])
async def test_missing_prompt_ack_is_uncertain_not_retryable_success(
    backend_factory, request_factory, tmp_path, mode
):
    backend = backend_factory(mode)
    short_commands(backend)
    outcome = await backend.run(request_factory(), no_events)
    assert outcome.state == "failed"
    assert "prompt" in outcome.error and "unknown" in outcome.error
    assert "synthetic-runtime-credential" not in outcome.error
    assert len([entry for entry in records(tmp_path) if entry.get("type") == "prompt"]) == 1
    assert backend._clients == set() and backend._runs == {}
