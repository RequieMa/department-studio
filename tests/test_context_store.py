import pytest

from department_studio.domain import Conflict
from department_studio.store import Store
from tests.factories import create_lead


def test_restart_keeps_completed_rotation_and_interrupts_unfinished_checks(tmp_path):
    path = tmp_path / "room.sqlite"
    native = tmp_path / "retained.jsonl"
    native.write_text("Private retained conversation\n")
    with Store(path) as store:
        first = create_lead(store, tmp_path, "atlas")
        second = create_lead(store, tmp_path, "canvas")
        note = store.post_human_message("@all Historical notes must not replay")
        batch_id, checks = store.begin_context_preparation()
        assert store.claim_context_check(checks[0].id)
        assert store.claim_context_check(checks[1].id)
        store.finish_context_check(checks[0].id, "reset", "Fresh context", str(native))
        fresh_id = store.get_lead(first.id).conversation_id
        assert fresh_id != first.conversation_id
        assert store.preparing and store.paused
    with Store(path) as store:
        store.recover()
        assert store.paused and not store.preparing
        assert [c.state for c in store.list_context_checks()] == ["reset", "interrupted"]
        assert store.get_lead(first.id).conversation_id == fresh_id
        assert store.get_lead(second.id).conversation_id == second.conversation_id
        assert store.get_message(note.message_id).text == "@all Historical notes must not replay"
        assert not store.list_deliveries()
        assert not store.finish_context_preparation(batch_id)
        assert store.list_session_refs(first.id)[0]["native_session_ref"] == str(native)
    assert native.read_text() == "Private retained conversation\n"


def test_context_reservations_apply_across_store_connections(tmp_path):
    path = tmp_path / "room.sqlite"
    with Store(path) as first, Store(path) as second:
        lead = create_lead(first, tmp_path)
        _, checks = first.begin_context_preparation()
        assert second.begin_context_preparation() is None
        for operation in (
            lambda: second.update_lead(lead.id, lead.revision, {"name": "Changed"}),
            lambda: second.delete_lead(lead.id, lead.revision),
            lambda: create_lead(second, tmp_path, "another"),
            second.resume,
        ):
            with pytest.raises(Conflict):
                operation()
        assert first.claim_context_check(checks[0].id)
        second.pause()
        with pytest.raises(Conflict):
            second.begin_context_preparation()
        first.finish_context_check(checks[0].id, "reset", "Stale result")
        assert first.get_lead(lead.id).conversation_id == lead.conversation_id
        assert first.paused


def test_late_preparation_batch_cannot_unpause_new_batch(tmp_path):
    with Store(tmp_path / "room.sqlite") as store:
        create_lead(store, tmp_path)
        old_id, old_checks = store.begin_context_preparation()
        store.pause()
        new_id, new_checks = store.begin_context_preparation()
        assert not store.finish_context_preparation(old_id)
        assert not store.claim_context_check(old_checks[0].id)
        assert store.paused and store.preparing
        assert store.claim_context_check(new_checks[0].id)
        store.finish_context_check(new_checks[0].id, "kept", "Ready")
        assert store.finish_context_preparation(new_id)
        assert not store.paused and not store.preparing
