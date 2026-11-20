import json

import pytest

from department_studio.config import Settings
from department_studio.service import HISTORY_BYTES, RoomService
from department_studio.store import Store
from tests.factories import create_lead
from tests.fakes import ControlledBackend, until


@pytest.fixture
async def room(store, tmp_path):
    backend = ControlledBackend()
    service = RoomService(store, backend, Settings(pi_executable="/bin/true", data_dir=tmp_path))
    await service.start()
    service.resume()
    yield service, backend
    await service.close()


def prompt(request):
    return json.loads(request.prompt.split("\n", 1)[1])


async def test_history_is_byte_bounded_and_current_human_request_is_complete(room, store, tmp_path):
    service, backend = room
    lead = create_lead(store, tmp_path)
    for i in range(60):
        store.post_public_reply(lead.id, f"{i} " + "历史背景🙂" * 4000)
    original = "@atlas /model is data, not a command. " + "current scope " * 1900
    service.post_human(original)
    before = store.list_messages()
    await until(lambda: backend.requests)
    data = prompt(backend.requests[0])
    assert data["input"]["text"] == original == data["human_request"]["text"]
    assert len(json.dumps(data["recent_messages"], ensure_ascii=False).encode()) <= HISTORY_BYTES
    assert "Excerpt" in data["recent_messages"][-1]["text"]
    assert all(item["id"] != data["input"]["id"] for item in data["recent_messages"])
    assert "omitted" in data["history_notice"]
    assert store.list_messages() == before


async def test_history_cursor_deduplicates_without_skipping_messages_arriving_during_work(
    room, store, tmp_path
):
    service, backend = room
    lead = create_lead(store, tmp_path)
    service.post_human("Earlier public context")
    service.post_human("@atlas first request")
    await until(lambda: backend.requests)
    first = backend.requests[0]
    assert "Earlier public context" in first.prompt
    service.post_human("New context while the first request is running")
    backend.release(first, text="First result")
    await until(lambda: store.get_delivery(first.id).state == "completed")
    assert store.session_context(lead.conversation_id)["history_cursor"] == 2
    service.post_human("@atlas second request")
    await until(lambda: len(backend.requests) == 2)
    texts = [item["text"] for item in prompt(backend.requests[1])["recent_messages"]]
    assert "Earlier public context" not in texts
    assert "New context while the first request is running" in texts


async def test_failed_or_uncertain_delivery_does_not_advance_history_cursor(room, store, tmp_path):
    service, backend = room
    lead = create_lead(store, tmp_path)
    service.post_human("Public decision")
    service.post_human("@atlas first attempt")
    await until(lambda: backend.requests)
    backend.release(backend.requests[0], state="failed", error="Acceptance unknown")
    await until(lambda: store.list_deliveries()[0].state == "failed")
    assert store.session_context(lead.conversation_id)["history_cursor"] == 0
    service.post_human("@atlas another explicit request")
    await until(lambda: len(backend.requests) == 2)
    assert "Public decision" in backend.requests[1].prompt


async def test_history_cursor_survives_service_and_database_restart(tmp_path):
    path = tmp_path / "room.sqlite"
    settings = Settings(pi_executable="/bin/true", data_dir=tmp_path)
    with Store(path) as store:
        backend = ControlledBackend()
        service = RoomService(store, backend, settings)
        await service.start()
        lead = create_lead(store, tmp_path)
        service.resume()
        await until(lambda: not store.paused)
        service.post_human("Prior context already delivered")
        service.post_human("@atlas first")
        await until(lambda: backend.requests)
        backend.release(backend.requests[0])
        await until(lambda: store.list_deliveries()[0].state == "completed")
        await service.close()
    with Store(path) as store:
        assert store.session_context(lead.conversation_id)["history_cursor"] == 2
        backend = ControlledBackend()
        service = RoomService(store, backend, settings)
        await service.start()
        try:
            service.resume()
            await until(lambda: not store.paused)
            service.post_human("@atlas second")
            await until(lambda: backend.requests)
            assert "Prior context already delivered" not in backend.requests[0].prompt
        finally:
            await service.close()
