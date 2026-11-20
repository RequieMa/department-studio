"""Task UI against real owner endpoints and synthetic runs; no API mocks."""

from pathlib import Path

import httpx
import pytest
from playwright.sync_api import expect

from tests.test_browser import ORIGIN, TOKEN
from tests.test_browser import browser as browser

pytestmark = pytest.mark.browser
ROOT = Path(__file__).resolve().parents[1]


def create_owner(client, handle):
    response = client.post(
        "/api/leads",
        json={
            "name": handle,
            "handle": handle,
            "role": "Synthetic task integration",
            "provider": "test",
            "model_id": "model-a",
            "workspace": str(ROOT),
        },
    )
    response.raise_for_status()
    return response.json()


def test_real_task_tree_note_fifo_draft_pause_and_reload(browser):
    with httpx.Client(base_url=ORIGIN, headers={"Authorization": "Bearer " + TOKEN}) as client:
        client.post("/api/room/pause").raise_for_status()
        first = create_owner(client, "task_real_one")
        second = create_owner(client, "task_real_two")
        source = client.post(
            "/api/messages",
            json={
                "text": "@task_real_one @task_real_two Original <script>literal</script>",
            },
        ).json()
        roots = [
            task
            for task in client.get("/api/tasks").json()["tasks"]
            if task["source_message_id"] == source["message_id"]
        ]
        assert len(roots) == 2
        assert len({task["source_chain_id"] for task in roots}) == 1
        root = next(task for task in roots if task["owner_lead_id"] == first["id"])
        context = browser.new_context(viewport={"width": 1600, "height": 1000})
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        try:
            page.goto(ORIGIN + "/#token=" + TOKEN)
            page.locator("#task-select-" + root["id"]).click()
            expect(page.locator("#task-context")).to_contain_text("<script>literal</script>")
            page.get_by_role("button", name="Create subtask", exact=True).click()
            page.get_by_label("Subtask title", exact=True).fill("Child <safe>")
            page.get_by_label("Responsible department", exact=True).select_option(second["id"])
            page.get_by_label("Subtask context", exact=True).fill("Durable child context")
            with page.expect_response(
                lambda response: (
                    response.request.method == "POST" and response.url.endswith("/api/tasks")
                )
            ) as response:
                page.get_by_role("button", name="Create task", exact=True).click()
            assert response.value.status == 201
            child = response.value.json()
            child_path = "/api/tasks/" + child["id"]
            expect(page.locator("#task-detail-title")).to_have_text("Child <safe>")
            expect(page.locator("#task-children-" + root["id"])).to_contain_text("Child <safe>")
            assert client.get(child_path).json()["deliveries"] == []
            composer = page.get_by_label("Instruction to responsible department", exact=True)
            composer.fill("A durable note @all is literal")
            page.get_by_role("button", name="Record note", exact=True).click()
            expect(page.locator("#task-instruction-receipt")).to_contain_text("No delivery created")
            client.post("/api/room/resume").raise_for_status()
            expect(page.locator("#task-instruction-send")).to_have_text("Send instruction")
            assert client.get(child_path).json()["deliveries"] == []
            composer.fill("synthetic wait: first active instruction")
            page.get_by_role("button", name="Send instruction", exact=True).click()
            expect(page.locator("#task-execution")).to_contain_text("running")
            composer.fill("Second instruction @task_real_one must not fan out")
            page.get_by_role("button", name="Queue instruction", exact=True).click()
            expect(page.locator("#task-execution")).to_contain_text("queued")
            detail = client.get(child_path).json()
            assert len(detail["deliveries"]) == 2
            assert {run["lead_id"] for run in detail["deliveries"]} == {second["id"]}
            assert {run["state"] for run in detail["deliveries"]} == {"running", "queued"}
            expect(page.get_by_role("button", name="Close task", exact=True)).to_be_disabled()
            assert (
                len(
                    [
                        task
                        for task in client.get("/api/tasks").json()["tasks"]
                        if task["source_message_id"] == source["message_id"]
                    ]
                )
                == 3
            )
            client.post("/api/room/pause").raise_for_status()
            expect(page.locator("#task-execution")).to_contain_text("canceled")
            client.post("/api/room/resume").raise_for_status()
            expect(page.locator("#task-instruction-send")).to_have_text("Send instruction")
            assert not any(
                run["state"] in {"queued", "running"}
                for run in client.get(child_path).json()["deliveries"]
            )
            composer.fill("Preserved draft through polling and resize")
            composer.focus()
            page.wait_for_timeout(1200)
            expect(composer).to_be_focused()
            page.set_viewport_size({"width": 390, "height": 844})
            expect(page.locator("#tasks-drawer")).to_be_visible()
            expect(composer).to_have_value("Preserved draft through polling and resize")
            expect(composer).to_be_focused()
            page.keyboard.press("Escape")
            expect(page.locator("#tasks-toggle")).to_be_focused()
            page.locator("#tasks-toggle").click()
            expect(composer).to_have_value("Preserved draft through polling and resize")
            page.reload()
            page.locator("#tasks-toggle").click()
            page.locator("#task-select-" + child["id"]).click()
            expect(page.locator("#task-context")).to_have_text("Durable child context")
            expect(page.locator("#task-instructions")).to_contain_text(
                "A durable note @all is literal"
            )
            expect(page.locator("#task-instructions")).to_contain_text("canceled")
            assert errors == []
        finally:
            client.post("/api/room/pause").raise_for_status()
            context.close()


def test_real_single_choice_is_explicit_resolved_once_and_public(browser):
    with httpx.Client(base_url=ORIGIN, headers={"Authorization": "Bearer " + TOKEN}) as client:
        client.post("/api/room/pause").raise_for_status()
        owner = create_owner(client, "choice_real")
        source = client.post("/api/messages", json={"text": "@choice_real Choose approach"}).json()
        task = next(
            task
            for task in client.get("/api/tasks").json()["tasks"]
            if task["source_message_id"] == source["message_id"]
        )
        ask = client.post(
            "/api/tasks/" + task["id"] + "/action-requests",
            json={
                "question": "Which approach <literal>?",
                "options": [{"id": "a", "label": "Approach A"}, {"id": "b", "label": "Approach B"}],
                "task_revision": 1,
                "idempotency_key": "browser-choice-real",
            },
        )
        ask.raise_for_status()
        context = browser.new_context(viewport={"width": 1600, "height": 1000})
        page = context.new_page()
        try:
            page.goto(ORIGIN + "/#token=" + TOKEN)
            expect(page.locator("#activity-count")).to_have_text("1")
            page.locator("#activity-toggle").click()
            group = page.get_by_role("group", name="Which approach <literal>?", exact=True)
            expect(group).to_be_visible()
            submit = page.get_by_role("button", name="Record decision as note", exact=True)
            expect(submit).to_be_disabled()
            group.get_by_label("Approach A", exact=True).check()
            group.get_by_label("Approach B", exact=True).check()
            expect(group.get_by_label("Approach A", exact=True)).not_to_be_checked()
            page.wait_for_timeout(1200)
            expect(group.get_by_label("Approach B", exact=True)).to_be_checked()
            with page.expect_response(
                lambda response: (
                    response.request.method == "POST" and response.url.endswith("/resolve")
                )
            ) as response:
                submit.click()
            assert response.value.status == 200
            receipt = response.value.json()["instruction"]
            assert receipt["delivery_id"] is None
            expect(group).not_to_be_visible()
            expect(page.locator("#activity-count")).to_be_hidden()
            detail = client.get("/api/tasks/" + task["id"]).json()
            assert len(detail["instructions"]) == 1
            assert detail["messages"][-1]["recipient_ids"] == [owner["id"]]
            assert detail["instructions"][0]["text"].endswith("Selected: Approach B")
            assert detail["action_requests"][0]["resolution"]["option_id"] == "b"
            page.reload()
            expect(page.locator("#activity-count")).to_be_hidden()
        finally:
            context.close()
