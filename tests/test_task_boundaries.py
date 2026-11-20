"""Boundary regressions for paginated public task history and decision provenance."""

import pytest

from department_studio.domain import Invalid
from tests.factories import create_lead
from tests.test_api import http_app as http_app
from tests.test_task_api import setup_task
from tests.test_tasks import instruct, root_task


def ask(store, task, key, **changes):
    return store.create_action_request(
        task["id"],
        **{
            "question": "Which approach?",
            "options": [{"id": "a", "label": "Alpha"}, {"id": "b", "label": "Beta"}],
            "task_revision": task["revision"],
            "idempotency_key": key,
            **changes,
        },
    )


@pytest.mark.parametrize("source", ["", "missing-message"])
def test_invalid_decision_source_is_rejected_without_partial_writes(store, tmp_path, source):
    _, task = root_task(store, tmp_path)
    with pytest.raises(Invalid, match="Source message must belong to this task"):
        ask(store, task, "bad-source", source_message_id=source)
    assert store.task_detail(task["id"])["action_requests"] == []
    # A rejected submission does not reserve the key.
    assert ask(store, task, "bad-source")["status"] == "open"


async def test_empty_decision_source_returns_422_not_server_error(http_app, tmp_path):
    client, _, _ = http_app
    _, task = await setup_task(client, tmp_path)
    response = await client.post(
        f"/api/tasks/{task['id']}/action-requests",
        json={
            "question": "Choose",
            "options": [{"id": "a", "label": "Alpha"}, {"id": "b", "label": "Beta"}],
            "task_revision": 1,
            "idempotency_key": "empty-source",
            "source_message_id": "",
        },
    )
    assert response.status_code == 422
    assert (await client.get("/api/action-requests")).json()["action_requests"] == []


def test_decision_source_requires_exact_task_not_shared_chain(store, tmp_path):
    create_lead(store, tmp_path)
    create_lead(store, tmp_path, "canvas")
    store.post_human_message("@all Shared root request")
    first, sibling = store.list_tasks()["tasks"]
    note = instruct(store, first, mode="record_note")
    with pytest.raises(Invalid, match="Source message must belong to this task"):
        ask(store, sibling, "foreign-source", source_message_id=note["message_id"])
    assert (
        ask(store, first, "own-source", source_message_id=note["message_id"])["source_message_id"]
        == note["message_id"]
    )


def test_detail_pages_preserve_instructions_without_unrelated_room_history(store, tmp_path):
    _, task = root_task(store, tmp_path)
    expected = []
    for number in range(6):
        expected.append(instruct(store, task, str(number), mode="record_note"))
        store.post_human_message(f"Unrelated public note {number}")
    cursor, messages, instructions = 0, [], []
    while True:
        page = store.task_detail(task["id"], cursor=cursor, limit=2)
        messages.extend(page["messages"])
        instructions.extend(page["instructions"])
        assert len(page["messages"]) <= 2
        assert page["deliveries"] == [] and not page["deliveries_truncated"]
        if page["next_cursor"] is None:
            break
        assert page["next_cursor"] > cursor
        cursor = page["next_cursor"]
    assert [entry["id"] for entry in instructions] == [entry["id"] for entry in expected]
    assert len(messages) == len({message["id"] for message in messages}) == 7
    assert not any("Unrelated public note" in message["text"] for message in messages)


def test_bounded_decision_history_and_actionable_pagination(store, tmp_path):
    _, task = root_task(store, tmp_path)
    requests = [ask(store, task, f"ask-{number}") for number in range(201)]
    detail = store.task_detail(task["id"])
    assert detail["action_requests_truncated"] is True
    assert [action["id"] for action in detail["action_requests"]] == [
        action["id"] for action in reversed(requests[1:])
    ]
    first = store.list_action_requests(limit=200)
    assert len(first["action_requests"]) == 200
    second = store.list_action_requests(cursor=first["next_cursor"], limit=200)
    assert [action["id"] for action in second["action_requests"]] == [requests[-1]["id"]]
    assert second["next_cursor"] is None
    store.update_task(task["id"], 1, {"lifecycle": "closed"})
    assert store.list_action_requests()["action_requests"] == []
    assert len(store.task_detail(task["id"])["action_requests"]) == 200
