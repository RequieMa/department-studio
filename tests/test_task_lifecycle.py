import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Barrier, Event

import pytest

from department_studio.domain import Conflict
from department_studio.store import Store
from tests.factories import create_lead
from tests.fakes import until
from tests.test_service import running as running
from tests.test_tasks import instruct, root_task


def action(store, task):
    return store.create_action_request(
        task["id"],
        question="Choose",
        options=[{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
        task_revision=task["revision"],
        idempotency_key="ask",
    )


def test_unavailable_actions_are_retained_but_not_actionable(store, tmp_path):
    lead, task = root_task(store, tmp_path)
    request = action(store, task)
    store.update_task(task["id"], 1, {"lifecycle": "closed"})
    assert store.list_action_requests()["action_requests"] == []
    assert store.task_detail(task["id"])["action_requests"][0]["status"] == "open"
    store.update_task(task["id"], 2, {"lifecycle": "open"})
    assert store.list_action_requests()["action_requests"][0]["id"] == request["id"]
    disabled = store.update_lead(lead.id, lead.revision, {"enabled": False})
    assert store.list_action_requests()["action_requests"] == []
    enabled = store.update_lead(lead.id, disabled.revision, {"enabled": True})
    assert len(store.list_action_requests()["action_requests"]) == 1
    store.delete_lead(lead.id, enabled.revision)
    assert store.list_action_requests()["action_requests"] == []
    assert store.task_detail(task["id"])["action_requests"][0]["status"] == "open"


def test_atomic_instruction_and_resolution_rollback(store, tmp_path):
    _, task = root_task(store, tmp_path)
    request = action(store, task)
    store.resume()
    with sqlite3.connect(tmp_path / "room.sqlite") as db:
        db.execute(
            "CREATE TRIGGER fail_receipt BEFORE INSERT ON task_requests "
            "BEGIN SELECT RAISE(ABORT, 'synthetic failure'); END"
        )
    before = store.snapshot()
    with pytest.raises(sqlite3.DatabaseError):
        store.resolve_action_request(
            request["id"],
            option_id="a",
            revision=1,
            task_revision=1,
            idempotency_key="answer",
            mode="execute",
        )
    assert store.snapshot() == before
    assert len(store.list_action_requests()["action_requests"]) == 1
    assert store.task_detail(task["id"])["instructions"] == []


def test_restart_cancels_work_and_preserves_receipts_without_replay(store, tmp_path):
    _, task = root_task(store, tmp_path)
    store.resume()
    note = instruct(store, task, "note", mode="record_note")
    first = instruct(store, task, "running")
    store.claim_delivery()
    second = instruct(store, task, "queued")
    with Store(tmp_path / "room.sqlite") as reopened:
        reopened.recover()
        assert reopened.paused
        assert reopened.get_delivery(first["delivery_id"]).state == "interrupted"
        assert reopened.get_delivery(second["delivery_id"]).state == "canceled"
        reopened.resume()
        assert instruct(reopened, task, "note", mode="record_note") == note
        assert instruct(reopened, task, "queued") == second
        assert reopened.claim_delivery() is None
        assert reopened.get_task(task["id"])["lifecycle"] == "open"


@pytest.mark.parametrize("guard", ["delete", "pause", "close", "retry", "resolve"])
@pytest.mark.parametrize("guard_first", [True, False])
def test_two_connection_writers_are_serialized(store, tmp_path, guard, guard_first):
    lead, task = root_task(store, tmp_path)
    store.resume()
    request = action(store, task) if guard == "resolve" else None
    with Store(tmp_path / "room.sqlite") as guarding, Store(tmp_path / "room.sqlite") as writing:
        locked, contender, barrier = Event(), Event(), Barrier(2)
        first = guarding if guard_first else writing
        transaction = first._transaction

        @contextmanager
        def held():
            with transaction():
                locked.set()
                assert contender.wait(3)
                yield

        first._transaction = held

        def write(db):
            if guard == "resolve":
                return db.resolve_action_request(
                    request["id"],
                    option_id="a",
                    revision=1,
                    task_revision=1,
                    idempotency_key="answer",
                    mode="execute",
                )
            return instruct(db, task)

        def guard_operation():
            if guard == "delete":
                return guarding.delete_lead(lead.id, lead.revision)
            if guard == "pause":
                return guarding.pause()
            if guard == "close":
                return guarding.update_task(task["id"], 1, {"lifecycle": "closed"})
            return write(guarding)

        def execute(is_guard):
            barrier.wait(timeout=3)
            if is_guard != guard_first:
                assert locked.wait(3)
                contender.set()
            try:
                return guard_operation() if is_guard else write(writing)
            except Conflict as exc:
                return exc

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(execute, flag) for flag in (True, False)]
            guarded, written = [future.result(timeout=5) for future in futures]
    if guard in {"retry", "resolve"}:
        assert guarded == written
        assert len(store.list_deliveries()) == 1
        assert len(store.task_detail(task["id"])["instructions"]) == 1
    elif guard_first:
        assert not isinstance(guarded, Exception)
        assert isinstance(written, Conflict)
        assert store.list_deliveries() == []
    else:
        assert not isinstance(written, Exception)
        if guard == "pause":
            assert store.get_delivery(written["delivery_id"]).state == "canceled"
        else:
            assert isinstance(guarded, Conflict)
            assert store.get_delivery(written["delivery_id"]).state == "queued"


async def test_task_prompt_fifo_context_and_peer_provenance(running, store, tmp_path):
    service, backend = running
    create_lead(store, tmp_path)
    create_lead(store, tmp_path, "canvas")
    service.post_human("@atlas original")
    await until(lambda: len(backend.requests) == 1)
    first = backend.requests[0]
    task = store.list_tasks()["tasks"][0]
    receipt = service.post_task_instruction(
        task["id"],
        text="Follow @canvas literally",
        task_revision=1,
        idempotency_key="follow",
        mode="execute",
    )
    store.update_task(task["id"], 1, {"context": "edited after queue"})
    assert len(backend.requests) == 1
    backend.release(first)
    await until(lambda: len(backend.requests) == 2)
    second = backend.requests[1]
    assert second.id == receipt["delivery_id"]
    data = json.loads(second.prompt.split("\n", 1)[1])
    assert data["task"]["context"] == "@atlas original"
    assert data["task"]["revision"] == 1
    assert data["human_request"]["text"] == "Follow @canvas literally"
    service.post_bridge(second.bridge_token, "peer", "Please review", ["canvas"])
    await until(lambda: len(backend.requests) == 3)
    peer = json.loads(backend.requests[2].prompt.split("\n", 1)[1])
    assert peer["task"] == data["task"]
    assert len(store.list_tasks()["tasks"]) == 1
    backend.release(second)
    backend.release(backend.requests[2])
    await until(lambda: all(d.state == "completed" for d in store.list_deliveries()))
    assert store.list_action_requests()["action_requests"] == []


async def test_stopping_owner_requires_explicit_note(running, store, tmp_path):
    service, backend = running
    backend.cancel_mode = "refuse"
    create_lead(store, tmp_path)
    service.post_human("@atlas original")
    await until(lambda: backend.requests)
    task = store.list_tasks()["tasks"][0]
    await service.pause()
    service.resume()
    assert store.get_task(task["id"])["instruction_action"]["reason"] == "owner_stopping"
    with pytest.raises(Conflict) as error:
        instruct(store, task)
    assert error.value.code == "owner_stopping"
    note = instruct(store, task, mode="record_note")
    assert note["delivery_id"] is None
    backend.release(backend.requests[0])
    await until(lambda: store.list_deliveries()[0].state == "interrupted")
    assert store.claim_delivery() is None
