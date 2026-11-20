import asyncio
from dataclasses import replace

import pytest

from department_studio.backends.rpc import RpcError
from tests.fakes import until
from tests.test_pi import backend_factory as backend_factory
from tests.test_pi import no_events, records
from tests.test_pi import request_factory as request_factory
from tests.test_rpc import rpc as rpc
from tests.test_rpc_robustness import short_commands


async def test_pre_prompt_compaction_can_outlast_the_command_deadline(
    backend_factory, request_factory, tmp_path
):
    backend = backend_factory("compaction_before_ack")
    backend.settings = replace(backend.settings, run_timeout_seconds=2)
    short_commands(backend)
    events = []

    async def capture(event):
        events.append(event)

    outcome = await backend.run(request_factory(), capture)
    assert outcome.state == "completed"
    assert any("compacting" in event.message for event in events)
    assert len([entry for entry in records(tmp_path) if entry.get("type") == "prompt"]) == 1
    assert "private" not in " ".join(event.message for event in events)
    assert backend._clients == set() and backend._runs == {}


async def test_compaction_never_removes_the_run_bound_or_invents_prompt_acceptance(
    backend_factory, request_factory, tmp_path
):
    backend = backend_factory("compaction_without_ack")
    backend.settings = replace(backend.settings, run_timeout_seconds=0.65)
    short_commands(backend)
    async with asyncio.timeout(2):
        outcome = await backend.run(request_factory(), no_events)
    assert outcome.state == "failed"
    assert "compacting" in outcome.error and "unknown" in outcome.error
    assert len([entry for entry in records(tmp_path) if entry.get("type") == "prompt"]) == 1
    assert backend._clients == set() and backend._runs == {}


async def test_stop_during_pre_prompt_compaction_still_clears_queue_and_confirms_exit(
    backend_factory, request_factory, tmp_path
):
    backend = backend_factory("compaction_without_ack")
    short_commands(backend)
    request = request_factory()
    run = asyncio.create_task(backend.run(request, no_events))
    await until(lambda: any(r.get("checkpoint") == "compaction_start" for r in records(tmp_path)))
    assert await backend.cancel(request.id)
    assert (await run).state == "interrupted"
    commands = [entry.get("type") for entry in records(tmp_path)]
    assert commands.index("clear_queue") < commands.index("abort")
    assert commands.count("prompt") == 1
    assert backend._clients == set() and backend._runs == {}


async def test_activity_does_not_extend_blocked_input_writes(rpc, monkeypatch):
    async def blocked_drain():
        await asyncio.Event().wait()

    monkeypatch.setattr(rpc.process.stdin, "drain", blocked_drain)
    activity = asyncio.Event()
    activity.set()
    async with asyncio.timeout(0.3):
        with pytest.raises(RpcError, match="writing input"):
            await rpc.command(
                "prompt", timeout=0.02, response_activity=activity, activity_timeout=1
            )
    assert rpc._pending == {}


@pytest.mark.parametrize("mode", ["length", "compaction_failed"])
async def test_exhausted_context_has_an_actionable_sanitized_failure(
    backend_factory, request_factory, mode
):
    backend = backend_factory(mode)
    events = []

    async def capture(event):
        events.append(event)

    outcome = await backend.run(request_factory(), capture)
    assert outcome.state == "failed" and outcome.text == ""
    assert "token limit" in outcome.error
    assert "conversation" in outcome.error
    if mode == "compaction_failed":
        assert "compaction failed" in outcome.error
        assert any("compaction failed" in event.message for event in events)
    combined = outcome.error + " ".join(event.message for event in events)
    assert "secret" not in combined and "private" not in combined


@pytest.mark.parametrize("mode", ["length_recovered", "compaction_after_success"])
async def test_compaction_does_not_hide_a_successful_settled_reply(
    backend_factory, request_factory, tmp_path, mode
):
    outcome = await backend_factory(mode).run(request_factory(), no_events)
    assert outcome.state == "completed" and outcome.text == "Synthetic public reply"
    assert len([entry for entry in records(tmp_path) if entry.get("type") == "prompt"]) == 1
