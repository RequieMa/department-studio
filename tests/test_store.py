import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from department_studio.domain import Conflict, Invalid
from department_studio.store import Store
from tests.factories import create_lead


def test_confirmed_stop_replaces_pending_notice_and_queued_work_is_never_running(store, tmp_path):
    create_lead(store, tmp_path)
    store.resume()
    store.post_human_message("@atlas first")
    running = store.claim_delivery()
    store.post_human_message("@atlas second")
    store.pause()
    assert "awaiting confirmed stop" in store.get_delivery(running.id).error
    store.confirm_stopped(running.id)
    stopped, canceled = store.list_deliveries()
    assert stopped.state == "interrupted"
    assert "stop confirmed" in stopped.error
    assert "awaiting" not in stopped.error
    assert canceled.state == "canceled"
    assert "before execution" in canceled.error
    assert "awaiting" not in canceled.error


def test_human_routing_is_explicit_exact_and_deduplicated(store, tmp_path):
    a = create_lead(store, tmp_path)
    b = create_lead(store, tmp_path, "canvas")
    create_lead(store, tmp_path, "rest", enabled=False)
    assert store.resolve_mentions("hello atlas user@canvas.com") == []
    assert store.resolve_mentions("@ATLAS, @atlas and @canvas!") == [a.id, b.id]
    assert store.resolve_mentions("@all") == [a.id, b.id]
    for text in ("@rest", "@unknown", "@atlas-suffix", "@abcdefgh" * 8):
        with pytest.raises(Invalid):
            store.resolve_mentions(text)


def test_unaddressed_and_final_posts_never_dispatch(store, tmp_path):
    a = create_lead(store, tmp_path)
    store.resume()
    post = store.post_human_message("Notes for everyone")
    assert post.recipient_ids == []
    store.post_public_reply(a.id, "@all @atlas a final public reply")
    assert store.list_deliveries() == []


def test_unknown_recipient_does_not_partially_commit(store, tmp_path):
    create_lead(store, tmp_path)
    store.resume()
    with pytest.raises(Invalid):
        store.post_human_message("@atlas @missing hello")
    assert store.list_messages() == []
    assert store.list_deliveries() == []


@pytest.mark.parametrize("text", ["", "  ", "a" * 32001])
def test_invalid_message_text(store, text):
    with pytest.raises(Invalid):
        store.post_human_message(text)


def test_initial_fanout_is_all_or_none(tmp_path):
    with Store(tmp_path / "room.sqlite", max_chain_deliveries=2) as store:
        for handle in ("atlas", "canvas", "kiln"):
            create_lead(store, tmp_path, handle)
        store.resume()
        post = store.post_human_message("@all review")
        assert post.recipient_ids == []
        assert "allowance" in post.notice.lower()
        assert len(store.list_messages()) == 1
        assert store.list_deliveries() == []


def test_bridge_commit_idempotency_and_altered_body_conflict(store, tmp_path):
    a = create_lead(store, tmp_path)
    b = create_lead(store, tmp_path, "canvas")
    store.resume()
    store.post_human_message("@atlas coordinate")
    run = store.claim_delivery()
    post = store.post_bridge_message(run.id, run.generation, "tool-1", "Contract?", ["canvas"])
    assert post.recipient_ids == [b.id]
    again = store.post_bridge_message(run.id, run.generation, "tool-1", "Contract?", ["canvas"])
    assert again == post
    assert len(store.list_messages()) == 2
    assert len(store.list_deliveries()) == 2
    message = store.get_message(post.message_id)
    assert message.sender_id == a.id
    assert message.sender_kind == "lead"
    with pytest.raises(Conflict, match="call_id"):
        store.post_bridge_message(run.id, run.generation, "tool-1", "Changed", ["canvas"])


def test_bridge_cannot_implicitly_broadcast_or_self_dispatch(store, tmp_path):
    create_lead(store, tmp_path)
    create_lead(store, tmp_path, "canvas")
    store.resume()
    store.post_human_message("@atlas work")
    run = store.claim_delivery()
    for call, recipients in (("info", []), ("self", ["atlas"])):
        result = store.post_bridge_message(
            run.id, run.generation, call, "@all @canvas FYI", recipients
        )
        assert result.recipient_ids == []
    assert len(store.list_deliveries()) == 1
    with pytest.raises(Invalid):
        store.post_bridge_message(run.id, run.generation, "all", "Broadcast", ["all"])


def test_concurrent_allowance_reservations_are_atomic(store, tmp_path):
    create_lead(store, tmp_path)
    for handle in ("canvas", "kiln", "forge"):
        create_lead(store, tmp_path, handle)
    store.resume()
    store.post_human_message("@atlas work")
    run = store.claim_delivery()

    def post(i):
        with Store(tmp_path / "room.sqlite") as concurrent:
            return concurrent.post_bridge_message(
                run.id, run.generation, str(i), f"Post {i}", ["canvas", "kiln", "forge"]
            )

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(post, range(8)))
    assert sorted(len(r.recipient_ids) for r in results) == [0] * 6 + [3, 3]
    assert len(store.list_messages()) == 9
    assert len(store.list_deliveries()) == 7
    assert store.get_chain(run.chain_id).reserved == 7


def test_database_failure_rolls_back_message_reservation_and_delivery(store, tmp_path):
    create_lead(store, tmp_path)
    store.resume()
    with sqlite3.connect(tmp_path / "room.sqlite") as db:
        db.execute(
            "CREATE TRIGGER fail_enqueue BEFORE INSERT ON deliveries "
            "BEGIN SELECT RAISE(ABORT, 'test fault'); END"
        )
    with pytest.raises(sqlite3.DatabaseError):
        store.post_human_message("@atlas work")
    assert store.list_messages() == []
    assert store.list_deliveries() == []


def test_pause_invalidates_posts_cancels_queues_and_requires_confirmed_stop(store, tmp_path):
    a = create_lead(store, tmp_path)
    store.resume()
    store.post_human_message("@atlas first")
    run = store.claim_delivery()
    store.post_human_message("@atlas second")
    store.pause()
    assert store.paused
    assert [d.state for d in store.list_deliveries()] == ["stopping", "canceled"]
    with pytest.raises(Conflict, match="generation"):
        store.post_bridge_message(run.id, run.generation, "late", "Too late", [])
    assert not store.finish_delivery(run.id, run.generation, "completed", text="Late result")
    assert len(store.list_messages()) == 2
    store.resume()
    assert store.claim_delivery() is None
    blocked = store.post_human_message("@atlas still blocked")
    assert blocked.notice and blocked.recipient_ids == []
    assert store.get_lead(a.id).status == "stopping"
    store.confirm_stopped(run.id)
    store.post_human_message("@atlas fresh request")
    assert store.claim_delivery().generation != run.generation


def test_public_message_while_paused_is_not_replayed(store, tmp_path):
    create_lead(store, tmp_path)
    result = store.post_human_message("@atlas later")
    assert result.recipient_ids == [] and result.notice
    store.resume()
    assert store.claim_delivery() is None


def test_final_completion_is_once_and_preserves_native_session(store, tmp_path):
    lead = create_lead(store, tmp_path)
    store.resume()
    store.post_human_message("@atlas work")
    run = store.claim_delivery()
    assert store.finish_delivery(
        run.id, run.generation, "completed", text="@all done", native_session_ref="opaque-reference"
    )
    assert not store.finish_delivery(run.id, run.generation, "completed", text="duplicate")
    assert len(store.list_messages()) == 2
    assert len(store.list_deliveries()) == 1
    assert store.list_session_refs(lead.id)[0]["native_session_ref"] == "opaque-reference"


def test_recovery_preserves_identity_labels_and_interrupts_uncertain_work(tmp_path):
    path = tmp_path / "room.sqlite"
    with Store(path) as first:
        lead = create_lead(first, tmp_path)
        first.post_public_reply(lead.id, "Historical")
        first.update_lead(lead.id, lead.revision, {"name": "Foundry", "handle": "forge"})
        first.resume()
        first.post_human_message("@forge work")
        first.claim_delivery()
        first.post_human_message("@forge queued")
    with Store(path) as reopened:
        reopened.recover()
        assert reopened.paused
        assert reopened.get_lead(lead.id).conversation_id == lead.conversation_id
        assert reopened.list_messages()[0].sender_name == "星图 Studio"
        assert [d.state for d in reopened.list_deliveries()] == ["interrupted", "canceled"]
        reopened.resume()
        assert reopened.claim_delivery() is None
