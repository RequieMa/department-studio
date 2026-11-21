import json
import sqlite3

import pytest

from department_studio.domain import Conflict, Invalid
from department_studio.store import Store
from tests.factories import create_lead


def root_task(store, tmp_path):
    lead = create_lead(store, tmp_path)
    store.post_human_message("@atlas original task")
    return lead, store.list_tasks()["tasks"][0]


def instruct(store, task, key="instruction", text="Follow up", mode="execute"):
    return store.post_task_instruction(
        task["id"], text=text, task_revision=task["revision"], idempotency_key=key, mode=mode
    )


def test_roots_share_chain_budget_and_have_exact_provenance(store, tmp_path):
    atlas = create_lead(store, tmp_path)
    canvas = create_lead(store, tmp_path, "canvas")
    store.resume()
    store.post_human_message("@all build <safe> things")
    tasks = store.list_tasks()["tasks"]
    assert len(tasks) == 2
    assert {t["owner_lead_id"] for t in tasks} == {atlas.id, canvas.id}
    assert len({t["source_chain_id"] for t in tasks}) == 1
    assert store.get_chain(tasks[0]["source_chain_id"]).reserved == 2
    first = store.claim_delivery()
    first_task = next(t for t in tasks if t["owner_lead_id"] == first.lead_id)
    sibling = next(t for t in tasks if t["id"] != first_task["id"])
    assert store.task_context_for_delivery(first.id)["id"] == first_task["id"]
    store.post_bridge_message(first.id, first.generation, "peer", "Peer context", ["canvas"])
    store.finish_delivery(first.id, first.generation, "completed", text="Final output")
    context = store.task_detail(first_task["id"])
    sibling_context = store.task_detail(sibling["id"])
    assert {m["text"] for m in context["messages"]} >= {"Peer context", "Final output"}
    assert {m["text"] for m in sibling_context["messages"]} == {"@all build <safe> things"}
    assert len(store.list_tasks()["tasks"]) == 2  # No inferred child from a handoff.
    assert "native_session_ref" not in json.dumps(context)


def test_child_metadata_only_revision_and_persistent_rename_history(store, tmp_path):
    lead, task = root_task(store, tmp_path)
    child_args = dict(
        parent_id=task["id"],
        parent_revision=1,
        owner_lead_id=lead.id,
        title="Explicit child",
        context="Public context",
        idempotency_key="child",
    )
    child = store.create_task(**child_args)
    assert store.create_task(**child_args) == child
    assert child["parent_id"] == task["id"] and child["root_id"] == task["id"]
    assert store.list_deliveries() == []
    renamed = store.update_lead(lead.id, lead.revision, {"name": "Renamed", "handle": "forge"})
    assert store.get_task(child["id"])["owner"]["handle"] == "forge"
    closed = store.update_task(child["id"], 1, {"lifecycle": "closed"})
    assert closed["revision"] == 2
    with pytest.raises(Conflict):
        store.update_task(child["id"], 1, {"title": "stale"})
    store.delete_lead(lead.id, renamed.revision)
    assert store.get_task(child["id"])["instruction_action"]["mode"] == "blocked"
    with Store(tmp_path / "room.sqlite") as reopened:
        assert reopened.get_task(child["id"])["lifecycle"] == "closed"
        assert reopened.get_task(task["id"])["owner"]["deleted_at"] is not None


def test_busy_instructions_queue_fifo_no_duplicate_no_auto_completion(store, tmp_path):
    lead, task = root_task(store, tmp_path)
    store.resume()
    first_receipt = instruct(store, task, "one", "First")
    first = store.claim_delivery()
    second_receipt = instruct(store, task, "two", "Second @all literal")
    assert instruct(store, task, "two", "Second @all literal") == second_receipt
    with pytest.raises(Conflict):
        instruct(store, task, "two", "Changed")
    assert first_receipt["chain_id"] != second_receipt["chain_id"]
    assert store.claim_delivery() is None
    assert store.get_message(second_receipt["message_id"]).recipient_ids == [lead.id]
    with pytest.raises(Conflict):
        store.update_task(task["id"], 1, {"lifecycle": "closed"})
    store.finish_delivery(first.id, first.generation, "completed", text="Done first run")
    second = store.claim_delivery()
    assert second.id == second_receipt["delivery_id"]
    assert store.get_task(task["id"])["lifecycle"] == "open"
    assert len(store.list_tasks()["tasks"]) == 1


def test_record_note_and_pause_race_never_create_latent_execution(store, tmp_path):
    _, task = root_task(store, tmp_path)
    with pytest.raises(Conflict):
        instruct(store, task)
    note = instruct(store, task, mode="record_note")
    assert note["disposition"] == "recorded_no_dispatch" and note["delivery_id"] is None
    store.resume()
    assert store.claim_delivery() is None
    assert instruct(store, task, mode="record_note") == note
    queued = instruct(store, task, "execute-after-resume")
    store.pause()
    store.resume()
    assert store.get_delivery(queued["delivery_id"]).state == "canceled"
    assert instruct(store, task, "execute-after-resume") == queued
    assert store.claim_delivery() is None
    assert store.task_detail(task["id"])["instructions"][-1]["delivery_state"] == "canceled"


def test_context_snapshot_survives_edits_and_recent_history_window(store, tmp_path):
    _, task = root_task(store, tmp_path)
    store.resume()
    receipt = instruct(store, task)
    store.update_task(task["id"], 1, {"context": "New context"})
    run = store.claim_delivery()
    assert run.id == receipt["delivery_id"]
    assert store.task_context_for_delivery(run.id)["context"] == "@atlas original task"


def test_action_requests_are_explicit_single_choice_atomic_and_idempotent(store, tmp_path):
    _, task = root_task(store, tmp_path)
    assert store.list_action_requests()["action_requests"] == []
    request = store.create_action_request(
        task["id"],
        question="Choose approach",
        options=[{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
        task_revision=1,
        idempotency_key="choice",
    )
    args = dict(
        option_id="a", revision=1, task_revision=1, idempotency_key="answer", mode="record_note"
    )
    with pytest.raises(Invalid):
        store.resolve_action_request(request["id"], **{**args, "option_id": "invalid"})
    assert len(store.list_action_requests()["action_requests"]) == 1
    resolution = store.resolve_action_request(request["id"], **args)
    assert store.resolve_action_request(request["id"], **args) == resolution
    assert resolution["instruction"]["disposition"] == "recorded_no_dispatch"
    assert store.list_action_requests()["action_requests"] == []
    assert store.list_deliveries() == []
    with pytest.raises(Conflict):
        store.resolve_action_request(request["id"], **{**args, "idempotency_key": "different"})
    assert store.task_detail(task["id"])["instructions"][-1]["text"].endswith("Selected: A")


def test_task_pagination_and_unknown_or_tombstoned_targets(store, tmp_path):
    lead, task = root_task(store, tmp_path)
    store.post_human_message("@atlas next")
    first = store.list_tasks(limit=1)
    assert len(first["tasks"]) == 1 and first["next_cursor"] is not None
    assert len(store.list_tasks(cursor=first["next_cursor"])["tasks"]) == 1
    store.delete_lead(lead.id, lead.revision)
    before = store.snapshot()
    with pytest.raises(Conflict):
        instruct(store, task, mode="record_note")
    assert store.snapshot() == before
    with sqlite3.connect(tmp_path / "room.sqlite") as db:
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
