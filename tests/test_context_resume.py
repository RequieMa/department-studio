import asyncio
import json

import pytest

from department_studio.backends.base import COMPACTING, AgentEvent, ContextOutcome
from department_studio.config import Settings
from department_studio.domain import Conflict
from department_studio.service import RoomService
from tests.factories import create_lead
from tests.fakes import ControlledBackend, until


class ContextBackend(ControlledBackend):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.checks = []
        self.context_pending = {}
        self.context_active = set()
        self.max_context_active = 0

    async def prepare_context(self, request, emit):
        self.checks.append(request)
        future = asyncio.get_running_loop().create_future()
        self.context_pending[request.id] = future
        self.context_active.add(request.id)
        self.max_context_active = max(self.max_context_active, len(self.context_active))
        await emit(AgentEvent("progress", COMPACTING))
        try:
            return await future
        finally:
            self.context_active.discard(request.id)

    def finish_check(self, request, action="kept"):
        self.context_pending[request.id].set_result(
            ContextOutcome(action, native_session_ref=f"/retained/{request.lead.conversation_id}")
        )

    async def cancel(self, run_id):
        if run_id not in self.context_pending:
            return await super().cancel(run_id)
        self.cancel_calls.append(run_id)
        if self.cancel_mode == "confirm":
            future = self.context_pending[run_id]
            if not future.done():
                future.set_result(ContextOutcome("interrupted"))
            return True
        if self.cancel_mode == "hang":
            await asyncio.Event().wait()
        return False

    async def close(self):
        for future in self.context_pending.values():
            if not future.done():
                future.set_result(ContextOutcome("interrupted"))
        await super().close()


@pytest.fixture
async def preparing(store, tmp_path):
    backend = ContextBackend()
    service = RoomService(
        store,
        backend,
        Settings(
            pi_executable="/bin/true",
            data_dir=tmp_path,
            run_timeout_seconds=2,
            stop_timeout_seconds=0.05,
        ),
    )
    await service.start()
    yield service, backend
    await service.close()


async def test_resume_prepares_every_enabled_department_before_work(preparing, store, tmp_path):
    service, backend = preparing
    leads = [create_lead(store, tmp_path, handle) for handle in ("atlas", "canvas", "kiln")]
    disabled = create_lead(store, tmp_path, "off")
    store.update_lead(disabled.id, disabled.revision, {"enabled": False})
    service.resume()
    await until(lambda: len(backend.checks) == 2)
    assert store.paused and store.preparing
    assert {store.get_lead(lead.id).status for lead in leads} == {"preparing"}
    service.resume()  # Repeated clicks do not start duplicate checks.
    note = service.post_human("@all a note during preparation")
    assert note.recipient_ids == []
    assert not backend.requests
    backend.finish_check(backend.checks[0], "compacted")
    await until(lambda: len(backend.checks) == 3)
    assert store.paused
    backend.finish_check(backend.checks[1], "reset")
    backend.finish_check(backend.checks[2])
    await until(lambda: not store.paused)
    assert not store.preparing and backend.max_context_active == 2
    assert len(backend.checks) == 3
    assert [c.state for c in store.list_context_checks()] == ["compacted", "reset", "kept"]
    assert store.get_lead(leads[0].id).conversation_id == leads[0].conversation_id
    assert store.get_lead(leads[1].id).conversation_id != leads[1].conversation_id
    refs = store.list_session_refs(leads[1].id)
    assert len(refs) == 2 and refs[0]["native_session_ref"].startswith("/retained/")
    assert refs[1]["previous_conversation_id"] == leads[1].conversation_id
    assert len(store.list_messages()) == 1 and not store.list_deliveries()
    service.post_human("@canvas continue the approved work")
    await until(lambda: backend.requests)
    prompt = json.loads(backend.requests[0].prompt.split("\n", 1)[1])
    assert prompt["continuity"]["previous_conversation_id"] == leads[1].conversation_id
    assert "retained" in prompt["continuity"]["native_session_ref"]


async def test_configuration_is_reserved_while_preparing(preparing, store, tmp_path):
    service, backend = preparing
    lead = create_lead(store, tmp_path)
    service.resume()
    await until(lambda: backend.checks)
    with pytest.raises(Conflict, match="prepar|busy"):
        store.update_lead(lead.id, lead.revision, {"name": "Changed"})
    with pytest.raises(Conflict, match="prepar|busy"):
        store.delete_lead(lead.id, lead.revision)
    with pytest.raises(Conflict, match="prepar"):
        create_lead(store, tmp_path, "another")


async def test_pause_cancels_preparation_and_never_rotates_or_replays(preparing, store, tmp_path):
    service, backend = preparing
    leads = [create_lead(store, tmp_path, handle) for handle in ("atlas", "canvas", "kiln")]
    service.resume()
    await until(lambda: len(backend.checks) == 2)
    await service.pause()
    await until(lambda: not backend.context_active)
    assert store.paused and not store.preparing
    assert len(backend.checks) == 2  # The queued third check was never launched.
    assert all(c.state == "interrupted" for c in store.list_context_checks())
    assert [store.get_lead(lead.id).conversation_id for lead in leads] == [
        lead.conversation_id for lead in leads
    ]
    assert not backend.requests and not store.list_deliveries()


@pytest.mark.parametrize("cancel_mode", ["refuse", "hang"])
async def test_unconfirmed_context_stop_blocks_resume_and_stale_reset(
    preparing, store, tmp_path, cancel_mode
):
    service, backend = preparing
    backend.cancel_mode = cancel_mode
    lead = create_lead(store, tmp_path)
    service.resume()
    await until(lambda: backend.checks)
    await service.pause()
    await until(lambda: backend.cancel_calls)
    assert store.get_lead(lead.id).status == "stopping"
    with pytest.raises(Conflict):
        service.resume()
    with pytest.raises(Conflict):
        store.update_lead(lead.id, lead.revision, {"name": "Changed"})
    backend.finish_check(backend.checks[0], "reset")
    await until(lambda: store.get_lead(lead.id).status == "idle")
    assert store.get_lead(lead.id).conversation_id == lead.conversation_id
    assert store.paused


async def test_failed_inspection_stays_paused_without_leaking_raw_error(preparing, store, tmp_path):
    service, backend = preparing
    create_lead(store, tmp_path)
    service.resume()
    await until(lambda: backend.checks)
    backend.context_pending[backend.checks[0].id].set_exception(
        RuntimeError("Authorization: Bearer private-provider-key")
    )
    await until(lambda: not store.preparing)
    assert store.paused
    assert store.list_context_checks()[0].state == "failed"
    assert "private-provider-key" not in json.dumps(store.snapshot())
    service.resume()
    await until(lambda: len(backend.checks) == 2)
    backend.finish_check(backend.checks[1])
    await until(lambda: not store.paused)


async def test_context_deadline_requires_confirmed_stop(store, tmp_path):
    backend = ContextBackend(cancel_mode="refuse")
    service = RoomService(
        store,
        backend,
        Settings(
            pi_executable="/bin/true",
            data_dir=tmp_path,
            run_timeout_seconds=0.05,
            stop_timeout_seconds=0.02,
        ),
    )
    await service.start()
    lead = create_lead(store, tmp_path)
    try:
        service.resume()
        await until(lambda: store.get_lead(lead.id).status == "stopping")
        assert store.paused
        with pytest.raises(Conflict):
            service.resume()
        backend.finish_check(backend.checks[0], "reset")
        await until(lambda: not store.preparing)
        assert store.paused and store.get_lead(lead.id).conversation_id == lead.conversation_id
    finally:
        await service.close()


async def test_shutdown_confirms_context_process_exit(preparing, store, tmp_path):
    service, backend = preparing
    create_lead(store, tmp_path)
    service.resume()
    await until(lambda: backend.checks)
    await service.close()
    assert service.shutdown_confirmed and backend.closed
    assert not backend.context_active and store.paused
    assert store.list_context_checks()[0].state == "interrupted"
