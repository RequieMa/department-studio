import asyncio
import json

import pytest

from department_studio.backends.base import AgentEvent, RunOutcome
from department_studio.config import Settings
from department_studio.domain import Conflict
from department_studio.service import RoomService
from tests.factories import create_lead
from tests.fakes import ControlledBackend, until


@pytest.fixture
async def running(store, tmp_path):
    backend = ControlledBackend()
    settings = Settings(
        pi_executable="/bin/true",
        data_dir=tmp_path,
        run_timeout_seconds=2,
        stop_timeout_seconds=0.1,
    )
    service = RoomService(store, backend, settings)
    await service.start()
    service.resume()
    yield service, backend
    await service.close()


async def test_global_concurrency_and_per_lead_serialization(running, store, tmp_path):
    service, backend = running
    for handle in ("atlas", "canvas", "kiln"):
        create_lead(store, tmp_path, handle)
    service.post_human("@all first")
    service.post_human("@atlas second")
    await until(lambda: len(backend.requests) == 2)
    assert len({r.lead.id for r in backend.requests}) == 2
    assert len({r.lead.conversation_id for r in backend.requests}) == 2
    backend.release(backend.requests[0])
    await until(lambda: len(backend.requests) == 3)
    assert backend.requests[2].lead.handle == "kiln"
    backend.release(backend.requests[1])
    await until(lambda: len(backend.requests) == 4)
    assert backend.requests[3].lead.handle == "atlas"
    assert backend.max_active == 2


async def test_attributed_prompt_preserves_origin_with_bounded_recent_context(
    running, store, tmp_path
):
    service, backend = running
    lead = create_lead(store, tmp_path)
    for i in range(55):
        store.post_public_reply(lead.id, f"history {i}")
    service.post_human("@atlas /model attacker-controlled")
    await until(lambda: backend.requests)
    prompt = backend.requests[0].prompt
    assert not prompt.startswith("/")
    data = json.loads(prompt.split("\n", 1)[1])
    assert data["input"]["sender_kind"] == "human"
    assert data["human_request"]["text"] == "@atlas /model attacker-controlled"
    assert 0 < len(data["recent_messages"]) < 50
    assert "background messages omitted" in data["history_notice"]
    assert data["recent_messages"][0]["sender_name"] == "星图 Studio"


async def test_bridge_post_carries_human_scope_and_final_text_never_routes(
    running, store, tmp_path
):
    service, backend = running
    create_lead(store, tmp_path)
    create_lead(store, tmp_path, "canvas")
    service.post_human("@atlas design an interface")
    await until(lambda: len(backend.requests) == 1)
    first = backend.requests[0]
    receipt = service.post_bridge(first.bridge_token, "tool-1", "Please review", ["canvas"])
    await until(lambda: len(backend.requests) == 2)
    peer = json.loads(backend.requests[1].prompt.split("\n", 1)[1])
    assert peer["input"]["sender_kind"] == "lead"
    assert peer["human_request"]["text"] == "@atlas design an interface"
    assert store.get_message(receipt.message_id).text == "Please review"
    backend.release(first, text="@all final only")
    backend.release(backend.requests[1], text="")
    await until(lambda: all(d.state == "completed" for d in store.list_deliveries()))
    assert len(store.list_deliveries()) == 2
    assert len(store.list_messages()) == 3


async def test_pause_blocks_claim_before_backend_start(running, store, tmp_path):
    service, backend = running
    create_lead(store, tmp_path)
    service.post_human("@atlas work")
    await service.pause()
    await asyncio.sleep(0.02)
    assert backend.requests == []
    assert store.list_deliveries()[0].state == "canceled"
    service.resume()
    await asyncio.sleep(0.02)
    assert backend.requests == []


async def test_pause_revokes_before_signaling_and_late_replies_are_diagnostic(
    running, store, tmp_path
):
    service, backend = running
    backend.cancel_mode = "refuse"
    create_lead(store, tmp_path)
    service.post_human("@atlas first")
    await until(lambda: backend.requests)
    run = backend.requests[0]
    service.post_human("@atlas queued")
    await service.pause()
    assert store.paused
    with pytest.raises(Conflict):
        service.post_bridge(run.bridge_token, "late", "must reject", [])
    await until(lambda: backend.cancel_calls)
    assert store.get_delivery(run.id).state == "stopping"
    with pytest.raises(Conflict):
        service.resume()
    backend.release(run, text="Late public content must not appear")
    await until(lambda: store.get_delivery(run.id).state == "interrupted")
    service.resume()
    await until(lambda: not store.paused)
    assert len(store.list_messages()) == 2
    assert store.get_delivery(run.id).diagnostic
    assert len(backend.requests) == 1


@pytest.mark.parametrize("cancel_mode", ["refuse", "hang"])
async def test_timeout_keeps_lead_unavailable_until_runtime_really_stops(
    store, tmp_path, cancel_mode
):
    backend = ControlledBackend(cancel_mode=cancel_mode)
    settings = Settings(
        pi_executable="/bin/true",
        data_dir=tmp_path,
        run_timeout_seconds=0.05,
        stop_timeout_seconds=0.02,
    )
    service = RoomService(store, backend, settings)
    await service.start()
    service.resume()
    create_lead(store, tmp_path)
    try:
        service.post_human("@atlas work")
        await until(lambda: backend.requests)
        run = backend.requests[0]
        await until(lambda: store.get_delivery(run.id).state == "stopping")
        assert not store.paused
        assert service.post_human("@atlas new request").recipient_ids == []
        assert len(backend.requests) == 1
        with pytest.raises(Conflict):
            service.post_bridge(run.bridge_token, "late", "reject", [])
        backend.release(run, text="Too late")
        await until(lambda: store.get_delivery(run.id).state == "interrupted")
        assert "Too late" not in [m.text for m in store.list_messages()]
        service.post_human("@atlas a fresh request")
        await until(lambda: len(backend.requests) == 2)
    finally:
        await service.close()


async def test_confirmed_abort_does_not_replay_queued_work(running, store, tmp_path):
    service, backend = running
    create_lead(store, tmp_path)
    service.post_human("@atlas first")
    await until(lambda: backend.requests)
    service.post_human("@atlas second")
    await service.pause()
    await until(lambda: store.list_deliveries()[0].state == "interrupted")
    service.resume()
    await asyncio.sleep(0.02)
    assert [d.state for d in store.list_deliveries()] == ["interrupted", "canceled"]
    assert len(backend.requests) == 1


async def test_backend_exception_is_failed_without_leaking_raw_error(running, store, tmp_path):
    service, backend = running
    create_lead(store, tmp_path)
    service.post_human("@atlas work")
    await until(lambda: backend.requests)
    run = backend.requests[0]
    backend.pending[run.id].set_exception(RuntimeError("Authorization: Bearer secret-value"))
    await until(lambda: store.get_delivery(run.id).state == "failed")
    assert "secret-value" not in json.dumps(store.snapshot())
    assert len(store.list_messages()) == 1


async def test_shutdown_stops_two_active_runs(running, store, tmp_path):
    service, backend = running
    create_lead(store, tmp_path)
    create_lead(store, tmp_path, "canvas")
    service.post_human("@all work")
    await until(lambda: len(backend.requests) == 2)
    await service.close()
    assert backend.closed
    assert not backend.active
    assert store.paused
    assert all(d.state == "interrupted" for d in store.list_deliveries())


async def test_unsupported_dialog_has_a_specific_safe_diagnostic(running, store, tmp_path):
    service, backend = running
    create_lead(store, tmp_path)

    async def dialog_run(request, emit):
        await emit(AgentEvent("error", "Unsupported runtime dialog canceled."))
        return RunOutcome("completed")

    backend.run = dialog_run
    service.post_human("@atlas work")
    await until(lambda: store.list_deliveries()[0].state == "completed")
    assert store.list_deliveries()[0].diagnostic == "Unsupported runtime dialog canceled."


@pytest.mark.parametrize(
    ("kind", "detail", "public"),
    [
        (
            "progress",
            "Runtime is compacting conversation history.",
            "Runtime is compacting conversation history.",
        ),
        (
            "error",
            "Conversation compaction failed; inspect retained work before retrying.",
            "Conversation compaction failed; inspect retained work before retrying.",
        ),
        (
            "error",
            "Conversation compaction was interrupted.",
            "Conversation compaction was interrupted.",
        ),
        (
            "error",
            "Conversation compaction failed: Authorization: Bearer private-token",
            "Runtime reported an error.",
        ),
    ],
)
async def test_only_fixed_compaction_diagnostics_reach_the_room(
    running, store, tmp_path, kind, detail, public
):
    service, backend = running
    create_lead(store, tmp_path)

    async def reporting(request, emit):
        await emit(AgentEvent(kind, detail))
        return RunOutcome("completed")

    backend.run = reporting
    service.post_human("@atlas work")
    await until(lambda: store.list_deliveries()[0].state == "completed")
    assert store.list_deliveries()[0].diagnostic == public
    assert "private-token" not in json.dumps(store.snapshot())
