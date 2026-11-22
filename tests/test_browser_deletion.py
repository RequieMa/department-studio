"""Deletion UI against real HTTP endpoints on the synthetic browser test server."""

from pathlib import Path

import httpx
import pytest
from playwright.sync_api import expect

from tests.test_browser import ORIGIN, TOKEN, wait_for_condition
from tests.test_browser import browser as browser

pytestmark = pytest.mark.browser
ROOT = Path(__file__).resolve().parents[1]


def test_real_endpoint_deletion_preserves_history_and_handles_stale_and_busy(browser):
    with httpx.Client(base_url=ORIGIN, headers={"Authorization": "Bearer " + TOKEN}) as client:
        client.post("/api/room/pause").raise_for_status()
        response = client.post(
            "/api/leads",
            json={
                "name": "Deletion integration",
                "handle": "deletion_integration",
                "role": "Synthetic deletion verification only",
                "provider": "test",
                "model_id": "model-a",
                "workspace": str(ROOT),
            },
        )
        response.raise_for_status()
        lead = response.json()
        path = f"/api/leads/{lead['id']}"
        history = "@deletion_integration keep this historical request"
        client.post("/api/messages", json={"text": history}).raise_for_status()

        context = browser.new_context()
        page = context.new_page()
        try:
            page.goto(ORIGIN + "/#token=" + TOKEN)
            composer = page.get_by_label("Message to the room", exact=True)
            composer.fill("Draft survives deletion")
            page.get_by_role("button", name="Edit Deletion integration", exact=True).click()
            department = page.get_by_role("dialog", name="Edit department")
            department.get_by_role("button", name="Delete department…", exact=True).click()
            confirmation = page.get_by_role("dialog", name="Delete department", exact=True)
            confirmation.get_by_label("Type the department handle to confirm", exact=True).fill(
                "@deletion_integration"
            )

            # A second owner tab changes configuration after this confirmation opened.
            update = client.patch(
                path,
                json={
                    **{
                        key: lead[key]
                        for key in (
                            "name",
                            "handle",
                            "role",
                            "provider",
                            "model_id",
                            "workspace",
                            "enabled",
                            "backend_kind",
                        )
                    },
                    "role": "Changed from another owner tab",
                    "revision": lead["revision"],
                },
            )
            update.raise_for_status()
            latest = update.json()
            with page.expect_response(
                lambda response: response.request.method == "DELETE"
            ) as deletion:
                confirmation.get_by_role("button", name="Delete department", exact=True).click()
            assert deletion.value.status == 409
            expect(confirmation).to_be_visible()
            expect(composer).to_have_value("Draft survives deletion")
            assert any(
                item["id"] == lead["id"] for item in client.get("/api/state").json()["leads"]
            )

            # Reopening explicitly obtains the current revision rather than silently retrying.
            page.reload()
            composer.fill("Draft survives deletion")
            page.get_by_role("button", name="Edit Deletion integration", exact=True).click()
            department.get_by_role("button", name="Delete department…", exact=True).click()
            confirmation.get_by_label("Type the department handle to confirm", exact=True).fill(
                "@deletion_integration"
            )
            with page.expect_response(
                lambda response: response.request.method == "DELETE"
            ) as deletion:
                confirmation.get_by_role("button", name="Delete department", exact=True).click()
            assert deletion.value.status == 200
            receipt = deletion.value.json()
            assert receipt["revision"] == latest["revision"] + 1
            expect(confirmation).not_to_be_visible()
            expect(composer).to_have_value("Draft survives deletion")
            expect(
                page.get_by_role("button", name="Edit Deletion integration", exact=True)
            ).to_have_count(0)
            expect(page.locator(".message-text").filter(has_text=history)).to_be_visible()
            state = client.get("/api/state").json()
            assert all(item["id"] != lead["id"] for item in state["leads"])
            assert client.delete(path, params={"revision": latest["revision"]}).json() == receipt
            assert (
                client.post("/api/messages", json={"text": "@deletion_integration"}).status_code
                == 422
            )
            assert (
                client.post("/api/messages", json={"text": "@all remaining only"}).status_code
                == 200
            )
            state = client.get("/api/state").json()
            assert lead["id"] not in state["messages"][-1]["recipient_ids"]

            # Real queued/running work must not be deleted through the UI or endpoint.
            busy = client.post(
                "/api/leads",
                json={
                    "name": "Busy deletion integration",
                    "handle": "deletion_busy",
                    "role": "Synthetic busy verification",
                    "provider": "test",
                    "model_id": "model-a",
                    "workspace": str(ROOT),
                },
            )
            busy.raise_for_status()
            busy_lead = busy.json()
            client.post("/api/room/resume").raise_for_status()
            wait_for_condition(page, lambda: not client.get("/api/state").json()["paused"])
            client.post(
                "/api/messages", json={"text": "@deletion_busy synthetic wait"}
            ).raise_for_status()
            page.reload()
            page.get_by_role("button", name="Edit Busy deletion integration", exact=True).click()
            department = page.get_by_role("dialog", name="Edit department")
            department.get_by_role("button", name="Delete department…", exact=True).click()
            expect(
                confirmation.get_by_role("button", name="Delete department", exact=True)
            ).to_be_disabled()
            assert (
                client.delete(
                    f"/api/leads/{busy_lead['id']}", params={"revision": busy_lead["revision"]}
                ).status_code
                == 409
            )
        finally:
            client.post("/api/room/pause").raise_for_status()
            context.close()
