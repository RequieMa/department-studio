import asyncio
from dataclasses import replace

import pytest

from department_studio.backends.base import COMPACTING, ContextRequest
from tests.fakes import until
from tests.test_pi import backend_factory as backend_factory
from tests.test_pi import no_events, records
from tests.test_pi import request_factory as request_factory


@pytest.mark.parametrize("mode", ["normal", "context_empty", "context_null_usage"])
async def test_healthy_context_does_not_call_a_model(
    backend_factory, request_factory, tmp_path, mode
):
    backend = backend_factory(mode)
    request = ContextRequest("context-1", request_factory().lead)
    outcome = await backend.prepare_context(request, no_events)
    assert outcome.action == "kept" and outcome.native_session_ref
    trace = records(tmp_path)
    launch = trace[0]
    assert "--no-tools" in launch["argv"] and "-e" not in launch["argv"]
    assert request.lead.conversation_id in launch["argv"]
    assert request.lead.model_id in launch["argv"]
    assert launch["bridge_token"] is None and not launch["owner_present"]
    assert not {"prompt", "compact", "new_session"} & {r.get("type") for r in trace}
    assert not backend._clients and not backend._runs


async def test_large_context_compacts_once_with_selected_model(
    backend_factory, request_factory, tmp_path
):
    backend = backend_factory("context_large")
    events = []

    async def capture(event):
        events.append(event)

    outcome = await backend.prepare_context(
        ContextRequest("context-1", request_factory().lead), capture
    )
    assert outcome.action == "compacted"
    assert any(e.message == COMPACTING for e in events)
    trace = records(tmp_path)
    assert len([r for r in trace if r.get("type") == "compact"]) == 1
    assert not any(r.get("type") == "prompt" for r in trace)
    assert not backend._clients and not backend._runs


@pytest.mark.parametrize(
    "mode", ["context_overflow", "context_failed", "context_ineffective", "context_bad_result"]
)
async def test_unrecoverable_context_requests_fresh_session_without_replaying(
    backend_factory, request_factory, tmp_path, mode
):
    backend = backend_factory(mode)
    outcome = await backend.prepare_context(
        ContextRequest("context-1", request_factory().lead), no_events
    )
    assert outcome.action == "reset" and outcome.native_session_ref
    trace = records(tmp_path)
    assert not any(r.get("type") in {"prompt", "new_session"} for r in trace)
    if mode == "context_overflow":
        assert not any(r.get("type") == "compact" for r in trace)
    assert not backend._clients and not backend._runs


@pytest.mark.parametrize(
    "mode", ["wrong_model", "context_wrong_session", "context_busy", "startup_exit"]
)
async def test_invalid_runtime_is_not_mistaken_for_discardable_context(
    backend_factory, request_factory, tmp_path, mode
):
    backend = backend_factory(mode)
    outcome = await backend.prepare_context(
        ContextRequest("context-1", request_factory().lead), no_events
    )
    assert outcome.action == "failed"
    assert not any(r.get("type") in {"prompt", "compact"} for r in records(tmp_path))


async def test_compaction_timeout_falls_back_after_confirmed_exit(backend_factory, request_factory):
    backend = backend_factory("context_hang")
    backend.settings = replace(backend.settings, run_timeout_seconds=0.2)
    async with asyncio.timeout(3):
        outcome = await backend.prepare_context(
            ContextRequest("context-1", request_factory().lead), no_events
        )
    assert outcome.action == "reset"
    assert not backend._clients and not backend._runs


async def test_cancel_context_compaction_preserves_conversation(
    backend_factory, request_factory, tmp_path
):
    backend = backend_factory("context_hang")
    request = ContextRequest("context-1", request_factory().lead)
    running = asyncio.create_task(backend.prepare_context(request, no_events))
    await until(lambda: any(r.get("type") == "compact" for r in records(tmp_path)))
    assert await backend.cancel(request.id)
    assert (await running).action == "interrupted"
    assert not backend._clients and not backend._runs
