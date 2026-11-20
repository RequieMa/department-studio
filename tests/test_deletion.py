import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime
from threading import Barrier, Event

import pytest

from department_studio.domain import Conflict, Invalid, NotFound
from department_studio.store import Store
from tests.factories import create_lead


def test_delete_preserves_history_identity_sessions_files_and_disabled_roster(store, tmp_path):
    lead = create_lead(store, tmp_path)
    disabled = create_lead(store, tmp_path, "disabled", enabled=False)
    workspace_file = tmp_path / "work.txt"
    native_file = tmp_path / "native.jsonl"
    workspace_file.write_text("keep work")
    native_file.write_text("keep native session")
    store.resume()
    store.post_human_message("@atlas work")
    delivery = store.claim_delivery()
    store.post_bridge_message(delivery.id, delivery.generation, "call", "A decision", [])
    store.finish_delivery(
        delivery.id,
        delivery.generation,
        "completed",
        text="Done",
        native_session_ref=str(native_file),
    )
    renamed = store.update_lead(lead.id, lead.revision, {"handle": "forge", "name": "Foundry"})
    other = tmp_path / "other"
    other.mkdir()
    lead = store.update_lead(lead.id, renamed.revision, {"workspace": str(other)})
    before = store.snapshot()
    refs = store.list_session_refs(lead.id)
    with sqlite3.connect(tmp_path / "room.sqlite") as db:
        receipts = db.execute("SELECT * FROM receipts").fetchall()
        generation = db.execute("SELECT generation FROM leads WHERE id=?", (lead.id,)).fetchone()
    receipt = store.delete_lead(lead.id, lead.revision)
    assert asdict(receipt) == {
        "id": lead.id,
        "revision": lead.revision + 1,
        "deleted_at": receipt.deleted_at,
    }
    assert datetime.fromisoformat(receipt.deleted_at).utcoffset().total_seconds() == 0
    assert store.snapshot()["messages"] == before["messages"]
    assert store.snapshot()["deliveries"] == before["deliveries"]
    assert store.snapshot()["leads"] == [asdict(disabled)]
    assert store.list_session_refs(lead.id) == refs
    historical = store.get_lead(lead.id, include_deleted=True)
    assert historical.id == lead.id and historical.conversation_id == lead.conversation_id
    assert historical.name == "Foundry" and historical.handle == "forge"
    assert historical.deleted_at == receipt.deleted_at and historical.status == "deleted"
    assert store.list_messages()[1].sender_handle == "atlas"
    assert workspace_file.read_text() == "keep work"
    assert native_file.read_text() == "keep native session"
    with sqlite3.connect(tmp_path / "room.sqlite") as db:
        assert db.execute("SELECT * FROM receipts").fetchall() == receipts
        assert (
            db.execute("SELECT generation FROM leads WHERE id=?", (lead.id,)).fetchone()
            == generation
        )
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    with Store(tmp_path / "room.sqlite") as reopened:
        assert reopened.list_leads() == [disabled]
        assert reopened.delete_lead(lead.id, lead.revision) == receipt
        assert reopened.delete_lead(lead.id, receipt.revision) == receipt
        assert reopened.list_session_refs(lead.id) == refs


@pytest.mark.parametrize("state", ["queued", "running", "stopping"])
def test_busy_delete_has_no_side_effects(store, tmp_path, state):
    lead = create_lead(store, tmp_path)
    store.resume()
    store.post_human_message("@atlas work")
    if state != "queued":
        store.claim_delivery()
    if state == "stopping":
        store.pause()
    before = store.snapshot()
    with pytest.raises(Conflict, match="busy"):
        store.delete_lead(lead.id, lead.revision)
    assert store.snapshot() == before


def test_delete_disabled_or_missing_workspace_and_reject_stale_or_unknown(store, tmp_path):
    folder = tmp_path / "workspace"
    folder.mkdir()
    lead = create_lead(store, folder, enabled=False)
    folder.rmdir()
    with pytest.raises(Conflict, match="revision"):
        store.delete_lead(lead.id, lead.revision + 1)
    with pytest.raises(NotFound):
        store.delete_lead("missing", 1)
    receipt = store.delete_lead(lead.id, lead.revision)
    assert receipt.revision == 2 and store.list_leads() == []
    assert store.delete_lead(lead.id, 999) == receipt


@pytest.mark.parametrize("revision", [True, False, 0, -1, 1.0, "1", None])
def test_store_delete_requires_positive_integer_revision(store, tmp_path, revision):
    lead = create_lead(store, tmp_path)
    with pytest.raises(Invalid):
        store.delete_lead(lead.id, revision)
    assert store.get_lead(lead.id) == lead


def test_tombstone_blocks_writes_reserves_current_handle_and_keeps_all_routing_atomic(
    store, tmp_path
):
    lead = create_lead(store, tmp_path)
    other = create_lead(store, tmp_path, "canvas")
    store.delete_lead(lead.id, lead.revision)
    for operation in (
        lambda: store.get_lead(lead.id),
        lambda: store.update_lead(lead.id, lead.revision, {"name": "Revived"}),
        lambda: store.post_public_reply(lead.id, "Cannot post"),
    ):
        with pytest.raises(NotFound):
            operation()
    with pytest.raises(Conflict, match="handle"):
        create_lead(store, tmp_path, "ATLAS")
    with pytest.raises(Conflict, match="handle"):
        store.update_lead(other.id, other.revision, {"handle": "atlas"})
    assert store.resolve_mentions("@all") == [other.id]
    store.resume()
    for text in ("@atlas", "@canvas @ATLAS"):
        with pytest.raises(Invalid):
            store.post_human_message(text)
    assert store.list_messages() == [] and store.list_deliveries() == []
    store.post_human_message("@canvas work")
    run = store.claim_delivery()
    before = store.snapshot()
    with pytest.raises(Invalid):
        store.post_bridge_message(run.id, run.generation, "new", "Ask deleted", ["canvas", "atlas"])
    assert store.snapshot() == before
    with sqlite3.connect(tmp_path / "room.sqlite") as db:
        assert db.execute("SELECT COUNT(*) FROM receipts").fetchone()[0] == 0


def test_confirmed_stop_allows_deletion_but_late_outcomes_stay_rejected(store, tmp_path):
    lead = create_lead(store, tmp_path)
    store.resume()
    store.post_human_message("@atlas running")
    run = store.claim_delivery()
    store.post_human_message("@atlas queued")
    store.pause()
    with pytest.raises(Conflict):
        store.delete_lead(lead.id, lead.revision)
    store.confirm_stopped(run.id)
    store.delete_lead(lead.id, lead.revision)
    store.resume()
    assert store.claim_delivery() is None
    with pytest.raises(Conflict):
        store.post_bridge_message(run.id, run.generation, "late", "Late", [])
    assert not store.finish_delivery(run.id, run.generation, "completed", text="Late")
    assert len(store.list_messages()) == 2
    assert [d.state for d in store.list_deliveries()] == ["interrupted", "canceled"]


def test_delete_failure_rolls_back_marker_and_revision(store, tmp_path):
    lead = create_lead(store, tmp_path)
    with sqlite3.connect(tmp_path / "room.sqlite") as db:
        db.execute(
            "CREATE TRIGGER fail_delete BEFORE UPDATE OF deleted_at ON leads "
            "BEGIN SELECT RAISE(ABORT, 'test fault'); END"
        )
    with pytest.raises(sqlite3.DatabaseError):
        store.delete_lead(lead.id, lead.revision)
    assert store.get_lead(lead.id) == lead


@pytest.mark.parametrize("operation", ["human", "bridge", "claim", "update"])
@pytest.mark.parametrize("delete_first", [True, False])
def test_deletion_serializes_with_other_writers(store, tmp_path, operation, delete_first):
    """Two connections, controlled lock ordering, no timing-dependent race winner."""
    target = create_lead(store, tmp_path)
    create_lead(store, tmp_path, "sender")
    store.resume()
    run = None
    if operation == "bridge":
        store.post_human_message("@sender work")
        run = store.claim_delivery()
    elif operation == "claim":
        store.post_human_message("@atlas work")
    path = tmp_path / "room.sqlite"
    with Store(path) as deleting, Store(path) as writing:
        locked, contender = Event(), Event()
        barrier = Barrier(2)
        first = deleting if delete_first else writing
        transaction = first._transaction

        # Pause the first writer AFTER BEGIN IMMEDIATE acquired the database lock.
        @contextmanager
        def holding_transaction():
            with transaction():
                locked.set()
                assert contender.wait(3)
                yield

        first._transaction = holding_transaction

        def delete():
            return deleting.delete_lead(target.id, target.revision)

        def write():
            if operation == "human":
                return writing.post_human_message("@atlas work")
            if operation == "bridge":
                return writing.post_bridge_message(run.id, run.generation, "call", "Ask", ["atlas"])
            if operation == "claim":
                return writing.claim_delivery()
            return writing.update_lead(target.id, target.revision, {"name": "Changed"})

        def execute(is_delete):
            barrier.wait(timeout=3)
            if is_delete != delete_first:
                assert locked.wait(3)
                contender.set()
            try:
                return (delete if is_delete else write)()
            except (Conflict, Invalid, NotFound) as exc:
                return exc

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(execute, flag) for flag in (True, False)]
            deletion, result = [f.result(timeout=5) for f in futures]
    if operation == "claim":
        # Even before claim, its queued delivery makes deletion illegal.
        assert isinstance(deletion, Conflict)
        assert result.lead_id == target.id and result.state == "running"
    elif delete_first:
        assert deletion.id == target.id
        assert isinstance(result, NotFound if operation == "update" else Invalid)
        assert not [d for d in store.list_deliveries() if d.lead_id == target.id]
    else:
        assert isinstance(deletion, Conflict)
        assert not isinstance(result, Exception)
        assert store.get_lead(target.id).deleted_at is None


def test_roster_read_tolerates_another_connection_deleting_mid_read(store, tmp_path, monkeypatch):
    lead = create_lead(store, tmp_path)
    with Store(tmp_path / "room.sqlite") as other:
        original = store.get_lead
        deleted = []

        def concurrent_delete(lead_id, **options):
            deleted.append(other.delete_lead(lead_id, lead.revision))
            return original(lead_id, **options)

        monkeypatch.setattr(store, "get_lead", concurrent_delete)
        assert store.snapshot()["leads"] == []
        assert len(deleted) == 1 and deleted[0].id == lead.id
        assert other.get_lead(lead.id, include_deleted=True).deleted_at == deleted[0].deleted_at


def test_defensive_dispatch_and_current_checks_ignore_tombstones(store, tmp_path):
    """Corrupt legacy writer fixtures must not make a deleted department execute."""
    lead = create_lead(store, tmp_path)
    store.resume()
    store.post_human_message("@atlas queued")
    with sqlite3.connect(tmp_path / "room.sqlite") as db:
        db.execute("UPDATE leads SET deleted_at='synthetic tombstone' WHERE id=?", (lead.id,))
    assert store.claim_delivery() is None
    with sqlite3.connect(tmp_path / "room.sqlite") as db:
        db.execute("UPDATE deliveries SET state='running'")
    delivery = store.list_deliveries()[0]
    assert not store.is_current(delivery.id, delivery.generation)
    with pytest.raises(Conflict):
        store.post_bridge_message(delivery.id, delivery.generation, "call", "Bad", [])
    assert not store.finish_delivery(delivery.id, delivery.generation, "completed", text="Bad")
